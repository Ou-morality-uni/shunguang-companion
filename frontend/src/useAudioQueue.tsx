import { createContext, useContext, useEffect, useRef, useState } from 'react';
import { request, type Features } from './api';
import { liveSpeech, PcmPlayback, SpeechSegmenter, streamSpeech, supportsLiveSpeech } from './speechStream';
import { SpokenTextFilter, spokenText } from './spokenText';

type Clip = { text: string; label: string; taskId?: string; expiresAt?: number };
type PlaybackGroup = { signature: string; clips: Clip[]; startedAt: number; firstAudioMs?: number };
type SpeechJob = {
  promise: Promise<string | null>;
  chunks: Uint8Array[];
  onAudio?: (bytes: Uint8Array) => void;
  abort?: AbortController;
};
type QueueItem = Clip & { group: PlaybackGroup; job?: SpeechJob; live?: boolean; cancelled?: boolean };
type ReplyPlayback = { group: PlaybackGroup } & (
  | { mode: 'whole' }
  | { mode: 'segmented'; segmenter: SpeechSegmenter; received: number }
  | {
      mode: 'live';
      segmenter: SpeechSegmenter;
      received: string;
      input?: ReturnType<typeof liveSpeech>;
      item?: QueueItem;
    }
);
// The existing /tts/stream and /tts/synthesize contracts accept at most 3000 code points.
const WHOLE_REPLY_LIMIT = 3000;
class PlaybackError extends Error {
  constructor(
    public kind: 'load' | 'blocked',
    message: string,
  ) {
    super(message);
  }
}
export type AudioController = {
  playing: boolean;
  busy: boolean;
  muted: boolean;
  error: string;
  label: string;
  queued: number;
  progress: number;
  duration: number;
  analyser: AnalyserNode | null;
  firstAudioMs: number | null;
  enqueue: (text: string, label?: string) => void;
  beginReply: () => void;
  appendReply: (text: string) => void;
  finishReply: (text: string) => void;
  stop: () => void;
  replay: () => void;
  toggleMute: () => void;
  enqueueWork: (event: { task_id: string; kind: string; text: string; created_at: string }) => void;
  cancelWork: (taskId: string) => void;
};
export const AudioContextValue = createContext<AudioController | null>(null);
export const useCompanionAudio = () => useContext(AudioContextValue)!;

/** Only session-local URLs are cached; no text or private media enters browser storage. */
export function useAudioQueue(settings?: Features['tts']): AudioController {
  const settingsRef = useRef(settings);
  settingsRef.current = settings;
  const signature = JSON.stringify(
    settings
      ? [
          settings.provider,
          settings.base_url,
          settings.model,
          settings.voice,
          settings.resource_id,
          settings.speed,
          settings.style,
          settings.reference_id,
          settings.reference_path,
          settings.reference_sha256,
          settings.reference_start,
          settings.reference_end,
          settings.reference_text,
          settings.external_reference_enabled,
          settings.use_model_key,
          settings.has_api_key,
          settings.enabled,
          settings.auto_play,
          settings.work_prompts,
          settings.muted,
          settings.timeout,
        ]
      : [],
  );
  const currentSignature = useRef(signature);
  currentSignature.current = signature;
  const previousSignature = useRef(signature);
  const element = useRef<HTMLAudioElement | null>(null);
  const context = useRef<AudioContext | null>(null);
  const source = useRef<MediaElementAudioSourceNode | null>(null);
  const queue = useRef<QueueItem[]>([]);
  const activeItem = useRef<QueueItem | null>(null);
  const replyText = useRef({ filter: new SpokenTextFilter(), raw: '', safe: '', offset: 0 });
  const last = useRef<PlaybackGroup | null>(null);
  const cache = useRef(new Map<string, string>());
  const working = useRef(false),
    generation = useRef(0);
  const requestAborts = useRef(new Set<AbortController>());
  const pcmPlayer = useRef<PcmPlayback | null>(null);
  const gain = useRef<GainNode | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const activeGroup = useRef<PlaybackGroup | null>(null);
  const reply = useRef<ReplyPlayback | null>(null);
  const flushTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const resolvePlayback = useRef<(() => void) | null>(null);
  const [playing, setPlaying] = useState(false),
    [busy, setBusy] = useState(false);
  const [muted, setMuted] = useState(false),
    [error, setError] = useState('');
  const [label, setLabel] = useState('等待播放'),
    [queued, setQueued] = useState(0);
  const [progress, setProgress] = useState(0),
    [duration, setDuration] = useState(0);
  const [analyser, setAnalyser] = useState<AnalyserNode | null>(null);
  const [firstAudioMs, setFirstAudioMs] = useState<number | null>(null);

  function audio() {
    if (!element.current) {
      const el = document.createElement('audio');
      el.dataset.companionPlayback = 'true';
      el.setAttribute('aria-hidden', 'true');
      el.style.display = 'none';
      el.preload = 'metadata';
      el.muted = muted;
      document.body.appendChild(el);
      element.current = el;
    }
    return element.current;
  }
  async function prepareGraph() {
    const el = audio();
    if (!context.current) {
      context.current = new window.AudioContext();
      const node = context.current.createAnalyser();
      node.fftSize = 128;
      source.current = context.current.createMediaElementSource(el);
      source.current.connect(node);
      gain.current = context.current.createGain();
      gain.current.gain.value = el.muted ? 0 : 1;
      node.connect(gain.current);
      gain.current.connect(context.current.destination);
      analyserRef.current = node;
      setAnalyser(node);
    }
    if (context.current.state === 'suspended') await context.current.resume();
  }
  function markFirstAudio(group: PlaybackGroup, delay = 0) {
    group.firstAudioMs ??= Math.round(performance.now() - group.startedAt + delay);
    setFirstAudioMs(group.firstAudioMs);
  }
  function cacheKey(item: QueueItem) {
    return item.group.signature + '\n' + item.text;
  }
  function remember(key: string, url: string) {
    cache.current.delete(key);
    cache.current.set(key, url);
    while (cache.current.size > 24) cache.current.delete(cache.current.keys().next().value!);
  }
  async function synthesize(item: QueueItem, token: number, onAudio?: (bytes: Uint8Array) => void) {
    const abort = new AbortController();
    if (item.job) item.job.abort = abort;
    requestAborts.current.add(abort);
    try {
      const result = onAudio
        ? { audio_url: await streamSpeech(item.text, abort.signal, onAudio) }
        : await request<{ audio_url: string }>('/tts/synthesize', {
            method: 'POST',
            body: JSON.stringify({ text: item.text }),
            signal: abort.signal,
          });
      if (token !== generation.current || item.cancelled || item.group.signature !== currentSignature.current)
        return null;
      const url = new URL(result.audio_url, window.location.origin);
      if (url.origin !== window.location.origin || !url.pathname.startsWith('/api/tts/audio/')) {
        throw new Error('语音服务返回了不可用的音频地址。');
      }
      remember(cacheKey(item), url.href);
      return url.href;
    } finally {
      requestAborts.current.delete(abort);
    }
  }
  function prepare(item: QueueItem | undefined, token: number) {
    if (
      !item ||
      item.cancelled ||
      (item.expiresAt && item.expiresAt < Date.now()) ||
      item.job ||
      cache.current.has(cacheKey(item))
    )
      return;
    const job: SpeechJob = { chunks: [], promise: Promise.resolve(null) };
    item.job = job;
    const streamed = !!settingsRef.current?.capabilities?.streaming_audio;
    job.promise = synthesize(
      item,
      token,
      streamed
        ? (bytes) => {
            if (token !== generation.current || item.cancelled) return;
            if (job.onAudio) job.onAudio(bytes);
            else job.chunks.push(bytes);
          }
        : undefined,
    );
    // Prefetch may reject before its turn is reached; drain still observes the original rejection.
    void job.promise.catch(() => {});
  }
  async function playStream(item: QueueItem, token: number) {
    await prepareGraph();
    if (token !== generation.current || item.cancelled) return;
    if (context.current!.state !== 'running')
      throw new PlaybackError('blocked', '浏览器暂未允许播放，请点击消息的播放按钮重试。');
    // Qwen-Audio already applies the configured rate upstream.
    const speed = item.live ? 1 : (settingsRef.current?.speed ?? 1);
    const player = new PcmPlayback(context.current!, analyserRef.current!, speed, item.live ? 0.35 : 0);
    pcmPlayer.current = player;
    const job = item.job!;
    job.onAudio = (bytes) => {
      if (token !== generation.current || item.cancelled) return;
      player.push(bytes);
      if (player.startedAt !== null) {
        markFirstAudio(item.group, Math.max(0, player.startedAt - context.current!.currentTime) * 1000);
        setPlaying(true);
        setDuration(player.seconds);
      }
    };
    job.chunks.splice(0).forEach(job.onAudio);
    const timer = window.setInterval(() => {
      if (player.startedAt !== null) {
        markFirstAudio(item.group, Math.max(0, player.startedAt - context.current!.currentTime) * 1000);
        setPlaying(true);
        setDuration(player.seconds);
        setProgress(
          Math.min(player.seconds, Math.max(0, context.current!.currentTime - player.startedAt) * speed),
        );
      }
    }, 100);
    try {
      const url = await job.promise;
      if (url && token === generation.current && !item.cancelled) await player.finish();
    } finally {
      clearInterval(timer);
      job.onAudio = undefined;
      player.stop();
      if (pcmPlayer.current === player) pcmPlayer.current = null;
    }
  }
  async function play(url: string, token: number, item?: QueueItem) {
    const el = audio();
    el.src = url;
    el.playbackRate = settingsRef.current?.speed ?? 1;
    await prepareGraph();
    if (token !== generation.current || item?.cancelled) return;
    await new Promise<void>((resolve, reject) => {
      resolvePlayback.current = resolve;
      el.onended = () => resolve();
      el.onerror = () => reject(new PlaybackError('load', '音频加载失败，请重播或检查语音服务。'));
      el.ontimeupdate = () => setProgress(el.currentTime);
      el.onloadedmetadata = () => setDuration(Number.isFinite(el.duration) ? el.duration : 0);
      el.play()
        .then(() => {
          if (token === generation.current) {
            setPlaying(true);
            if (activeGroup.current) markFirstAudio(activeGroup.current);
          }
        })
        .catch((failure: Error) =>
          reject(
            failure.name === 'NotAllowedError'
              ? new PlaybackError('blocked', '浏览器暂未允许播放，请点击消息的播放按钮重试。')
              : new PlaybackError('load', '音频加载失败，请重播或检查语音服务。'),
          ),
        );
    });
  }
  async function missing(url: string) {
    const abort = new AbortController();
    requestAborts.current.add(abort);
    try {
      const response = await fetch(url, { signal: abort.signal, cache: 'no-store' });
      const absent = response.status === 404;
      await response.body?.cancel();
      return absent;
    } finally {
      requestAborts.current.delete(abort);
    }
  }
  async function drain() {
    if (working.current) return;
    working.current = true;
    const token = generation.current;
    try {
      while (queue.current.length && token === generation.current) {
        const item = queue.current.shift()!;
        if (
          item.group.signature !== currentSignature.current ||
          item.cancelled ||
          (item.expiresAt && item.expiresAt < Date.now())
        ) {
          item.job?.abort?.abort();
          continue;
        }
        activeItem.current = item;
        activeGroup.current = item.group;
        prepare(item, token);
        if (settingsRef.current?.provider !== 'mimo') prepare(queue.current[0], token);
        setQueued(queue.current.length);
        setBusy(true);
        setLabel(item.label);
        setFirstAudioMs(item.group.firstAudioMs ?? null);
        setError('');
        setProgress(0);
        setDuration(0);
        try {
          const key = cacheKey(item),
            cached = cache.current.get(key);
          last.current = item.group;
          if (!cached && (item.live || settingsRef.current?.capabilities?.streaming_audio)) {
            await playStream(item, token);
            continue;
          }
          const url = cached || (await item.job!.promise);
          if (!url || token !== generation.current) break;
          remember(key, url);
          last.current = item.group;
          try {
            await play(url, token, item);
          } catch (failure) {
            // A removed cached file may be recreated once. Autoplay or network errors
            // never trigger another billed synthesis automatically.
            if (
              cached &&
              failure instanceof PlaybackError &&
              failure.kind === 'load' &&
              token === generation.current &&
              (await missing(url))
            ) {
              cache.current.delete(key);
              const replacement = await synthesize(item, token);
              if (replacement && token === generation.current) await play(replacement, token, item);
            } else throw failure;
          }
        } catch (failure) {
          if (token === generation.current && (failure as Error).name !== 'AbortError') {
            if (!item.taskId) stop();
            else pcmPlayer.current?.stop();
            setError((failure as Error).message);
          }
        } finally {
          resolvePlayback.current = null;
          activeItem.current = null;
          setPlaying(false);
        }
      }
    } finally {
      working.current = false;
      setBusy(false);
      if (queue.current.length) void drain();
    }
  }
  function ready() {
    const valid =
      settings?.enabled &&
      settings.has_api_key &&
      ((settings.provider === 'mimo' &&
        settings.model === 'mimo-v2.5-tts-voiceclone' &&
        settings.external_reference_enabled &&
        settings.reference_path) ||
        (settings.provider === 'aliyun' && settings.voice && settings.model));
    if (!valid) setError('请先启用语音并保存该厂商的密钥、克隆模型和参考音频或音色 ID。');
    return !!valid;
  }
  function group(): PlaybackGroup {
    return { signature: currentSignature.current, clips: [], startedAt: performance.now() };
  }
  function addChunks(
    chunks: string[],
    playback: PlaybackGroup,
    label = '叶瞬光的回应',
    metadata: { taskId?: string; expiresAt?: number } = {},
  ) {
    if (playback.signature !== currentSignature.current) return;
    const clips = chunks.map((text) => ({ text, label, ...metadata }));
    playback.clips.push(...clips);
    queue.current.push(...clips.map((clip) => ({ ...clip, group: playback })));
    setQueued(queue.current.length);
    if (working.current && settingsRef.current?.provider !== 'mimo')
      prepare(queue.current[0], generation.current);
    void drain();
  }
  function enqueue(text: string, itemLabel = '叶瞬光的回应') {
    text = spokenText(text).trim();
    if (!text || !ready()) return;
    if (settingsRef.current?.provider === 'aliyun') {
      if (!validWholeReply(text)) return;
      void prepareGraph().catch(() => {});
      addChunks([text], group(), itemLabel);
      return;
    }
    if (text.length > 12000) {
      setError('这条回复较长，请复制所需段落；单次播放最多 12000 字。');
      return;
    }
    void prepareGraph().catch(() => {});
    addChunks(
      new SpeechSegmenter(settingsRef.current?.provider === 'mimo' ? 70 : 0).push(text, true),
      group(),
      itemLabel,
    );
  }
  function beginReply() {
    stop();
    replyText.current = { filter: new SpokenTextFilter(), raw: '', safe: '', offset: 0 };
    setFirstAudioMs(null);
    if (!settings?.enabled || !settings.auto_play || muted || !ready()) return;
    void prepareGraph().catch(() => {});
    reply.current = newReply();
  }
  function newReply(): ReplyPlayback {
    return settingsRef.current?.provider === 'aliyun'
      ? supportsLiveSpeech(settingsRef.current.model)
        ? { mode: 'live', group: group(), segmenter: new SpeechSegmenter(40, true), received: '' }
        : { mode: 'whole', group: group() }
      : {
          mode: 'segmented',
          segmenter: new SpeechSegmenter(settingsRef.current?.provider === 'mimo' ? 70 : 0),
          group: group(),
          received: 0,
        };
  }
  function appendReply(text: string) {
    const current = reply.current;
    if (!current) return;
    replyText.current.raw += text;
    text = replyText.current.filter.push(text);
    replyText.current.safe += text;
    if (current.mode === 'whole' || !text) return;
    if (current.mode === 'live') {
      current.received += text;
      if (!validWholeReply(current.received)) {
        stop();
        return;
      }
      feedLive(current, current.segmenter.push(text));
      if (!flushTimer.current)
        flushTimer.current = setTimeout(() => {
          flushTimer.current = null;
          if (reply.current === current) feedLive(current, current.segmenter.push('', true));
        }, 600);
      return;
    }
    current.received += text.length;
    if (current.received > 12000) {
      stop();
      setError('自动朗读已达到单条 12000 字上限。');
      return;
    }
    addChunks(current.segmenter.push(text), current.group);
    if (!flushTimer.current)
      flushTimer.current = setTimeout(
        () => {
          flushTimer.current = null;
          if (reply.current === current) addChunks(current.segmenter.push('', true), current.group);
        },
        settingsRef.current?.provider === 'mimo' ? 2400 : 700,
      );
  }
  function finishReply(text: string) {
    const current = reply.current;
    if (!current) return;
    text = spokenText(text).slice(replyText.current.offset);
    if (flushTimer.current) clearTimeout(flushTimer.current);
    flushTimer.current = null;
    reply.current = null;
    if (current.mode === 'live') {
      if (!text.startsWith(current.received) || !validWholeReply(text)) {
        stop();
        setError('最终文字发生变化或超出朗读上限，已停止语音；可手动播放完整回复。');
        return;
      }
      feedLive(current, current.segmenter.push(text.slice(current.received.length), true));
      if (current.item) current.item.text = text;
      current.input?.finish();
      return;
    }
    if (current.mode === 'whole') {
      text = text.trim();
      if (text && validWholeReply(text)) addChunks([text], current.group);
      return;
    }
    // Some backends return only the final record. Never read the whole answer twice.
    if (!current.received && text.length <= 12000)
      addChunks(current.segmenter.push(text, true), current.group);
    else addChunks(current.segmenter.push(text.slice(current.received), true), current.group);
  }
  function pauseReply() {
    const current = reply.current;
    if (!current) return;
    if (flushTimer.current) clearTimeout(flushTimer.current);
    flushTimer.current = null;
    if (current.mode === 'live') {
      feedLive(current, current.segmenter.push('', true));
      if (current.item) current.item.text = current.received;
      current.input?.finish();
    } else if (current.mode === 'segmented') addChunks(current.segmenter.push('', true), current.group);
    else {
      const text = replyText.current.safe.slice(replyText.current.offset).trim();
      if (text && validWholeReply(text)) addChunks([text], current.group);
    }
    replyText.current.offset = replyText.current.safe.length;
    reply.current = newReply();
  }
  function cancelWork(taskId: string) {
    queue.current = queue.current.filter((item) => {
      if (item.taskId !== taskId) return true;
      item.cancelled = true;
      item.job?.abort?.abort();
      return false;
    });
    setQueued(queue.current.length);
    const item = activeItem.current;
    if (item?.taskId === taskId) {
      item.cancelled = true;
      item.job?.abort?.abort();
      pcmPlayer.current?.stop();
      element.current?.pause();
      resolvePlayback.current?.();
    }
  }
  function enqueueWork(event: { task_id: string; kind: string; text: string; created_at: string }) {
    const age = Date.now() - new Date(event.created_at).getTime();
    const terminal = [
      'complete',
      'partial',
      'failed',
      'cancelled',
      'restored',
      'authorization',
      'waiting_limit',
      'waiting_output',
    ].includes(event.kind);
    if (terminal) cancelWork(event.task_id);
    if (!settingsRef.current?.enabled || muted || (age > 30000 && event.kind !== 'summary')) return;
    if (
      event.kind === 'summary' ? !settingsRef.current.auto_play : settingsRef.current.work_prompts === false
    )
      return;
    if (!ready()) return;
    pauseReply();
    void prepareGraph().catch(() => {});
    const text = spokenText(event.text).trim();
    if (settingsRef.current.provider === 'aliyun' && !validWholeReply(text)) return;
    if (text.length > 12000) return;
    const chunks =
      settingsRef.current.provider === 'aliyun' ? [text] : new SpeechSegmenter(70).push(text, true);
    addChunks(
      chunks.filter(Boolean),
      group(),
      event.kind === 'summary' ? '瞬光的资料整理' : '瞬光的工作提示',
      {
        taskId: event.task_id,
        expiresAt:
          event.kind === 'summary'
            ? undefined
            : Date.now() + (terminal || event.kind === 'authorization' ? 30000 : 8000),
      },
    );
  }
  function feedLive(current: Extract<ReplyPlayback, { mode: 'live' }>, parts: string[]) {
    if (!parts.length) return;
    if (!current.input) {
      const token = generation.current;
      const abort = new AbortController();
      requestAborts.current.add(abort);
      const job: SpeechJob = { chunks: [], promise: Promise.resolve(null) };
      const item: QueueItem = { text: '', label: '叶瞬光的回应', group: current.group, job, live: true };
      current.item = item;
      current.group.clips.push(item);
      current.input = liveSpeech(abort.signal, (bytes) => {
        if (token !== generation.current) return;
        if (job.onAudio) job.onAudio(bytes);
        else job.chunks.push(bytes);
      });
      job.promise = current.input.promise
        .then((value) => {
          if (token !== generation.current || current.group.signature !== currentSignature.current)
            return null;
          const url = new URL(value, window.location.origin);
          if (url.origin !== window.location.origin || !url.pathname.startsWith('/api/tts/audio/'))
            throw new Error('语音服务返回了不可用的音频地址。');
          remember(cacheKey(item), url.href);
          return url.href;
        })
        .finally(() => requestAborts.current.delete(abort));
      void job.promise.catch(() => {});
      queue.current.push(item);
      setQueued(queue.current.length);
      void drain();
    }
    parts.forEach((part) => current.input!.push(part));
  }
  function validWholeReply(text: string) {
    if (Array.from(text).length <= WHOLE_REPLY_LIMIT) return true;
    setError(`百炼单条朗读最多 ${WHOLE_REPLY_LIMIT} 个字符；这条回复过长，请选择较短的内容播放。`);
    return false;
  }
  function stop() {
    generation.current++;
    reply.current = null;
    if (flushTimer.current) clearTimeout(flushTimer.current);
    flushTimer.current = null;
    queue.current = [];
    setQueued(0);
    requestAborts.current.forEach((abort) => abort.abort());
    requestAborts.current.clear();
    pcmPlayer.current?.stop();
    const el = element.current;
    if (el) {
      el.pause();
      el.removeAttribute('src');
      el.load();
    }
    resolvePlayback.current?.();
    setPlaying(false);
    setBusy(false);
    setProgress(0);
  }
  function replay() {
    const group = last.current;
    if (!group || group.signature !== currentSignature.current) {
      setError('请先播放一条当前配置生成的语音。');
      return;
    }
    if (group.clips.some((clip) => !clip.text.trim())) {
      setError('这条语音尚未完整生成，请在回复完成后点击消息的播放按钮。');
      return;
    }
    stop();
    group.startedAt = performance.now();
    group.firstAudioMs = undefined;
    void prepareGraph().catch(() => {});
    queue.current.push(...group.clips.map(({ text, label }) => ({ text, label, group })));
    setQueued(queue.current.length);
    setError('');
    void drain();
  }
  function toggleMute() {
    const next = !muted;
    setMuted(next);
    audio().muted = next;
    if (gain.current) gain.current.gain.value = next ? 0 : 1;
    if (next) stop();
  }
  useEffect(() => {
    setMuted(!!settings?.muted);
    if (element.current) element.current.muted = !!settings?.muted;
    if (gain.current) gain.current.gain.value = settings?.muted ? 0 : 1;
  }, [settings?.muted]);
  useEffect(() => {
    if (previousSignature.current !== signature) {
      previousSignature.current = signature;
      stop();
      cache.current.clear();
      last.current = null;
    }
  }, [signature]);
  useEffect(
    () => () => {
      generation.current++;
      queue.current = [];
      cache.current.clear();
      requestAborts.current.forEach((abort) => abort.abort());
      if (flushTimer.current) clearTimeout(flushTimer.current);
      pcmPlayer.current?.stop();
      resolvePlayback.current?.();
      const el = element.current;
      if (el) {
        el.pause();
        el.onended = null;
        el.onerror = null;
        el.ontimeupdate = null;
        el.onloadedmetadata = null;
        el.remove();
      }
      element.current = null;
      void context.current?.close();
      context.current = null;
      source.current = null;
    },
    [],
  );
  return {
    playing,
    busy,
    muted,
    error,
    label,
    queued,
    progress,
    duration,
    analyser,
    firstAudioMs,
    enqueue,
    beginReply,
    appendReply,
    finishReply,
    stop,
    replay,
    toggleMute,
    enqueueWork,
    cancelWork,
  };
}
