import { createContext, useContext, useEffect, useRef, useState } from 'react';
import { request, type Features } from './api';

type Clip = { text: string; label: string };
type PlaybackGroup = { signature: string; clips: Clip[] };
type QueueItem = Clip & { group: PlaybackGroup };
class PlaybackError extends Error {
  constructor(public kind: 'load' | 'blocked', message: string) { super(message); }
}
export type AudioController = {
  playing: boolean; busy: boolean; muted: boolean; error: string; label: string;
  queued: number; progress: number; duration: number; analyser: AnalyserNode | null;
  enqueue: (text: string, label?: string) => void; stop: () => void;
  replay: () => void; toggleMute: () => void;
};
export const AudioContextValue = createContext<AudioController | null>(null);
export const useCompanionAudio = () => useContext(AudioContextValue)!;

/** Only session-local URLs are cached; no text or private media enters browser storage. */
export function useAudioQueue(settings?: Features['tts']): AudioController {
  const signature = JSON.stringify(settings ? [
    settings.provider, settings.base_url, settings.model, settings.voice, settings.speed,
    settings.style, settings.reference_id, settings.reference_path, settings.reference_sha256, settings.reference_start, settings.reference_end,
    settings.reference_text, settings.external_reference_enabled, settings.use_model_key,
    settings.has_api_key, settings.enabled, settings.auto_play, settings.muted, settings.timeout,
  ] : []);
  const currentSignature = useRef(signature); currentSignature.current = signature;
  const previousSignature = useRef(signature);
  const element = useRef<HTMLAudioElement | null>(null);
  const context = useRef<AudioContext | null>(null);
  const source = useRef<MediaElementAudioSourceNode | null>(null);
  const queue = useRef<QueueItem[]>([]);
  const last = useRef<PlaybackGroup | null>(null);
  const cache = useRef(new Map<string, string>());
  const working = useRef(false), generation = useRef(0);
  const requestAbort = useRef<AbortController | null>(null);
  const resolvePlayback = useRef<(() => void) | null>(null);
  const [playing, setPlaying] = useState(false), [busy, setBusy] = useState(false);
  const [muted, setMuted] = useState(false), [error, setError] = useState('');
  const [label, setLabel] = useState('等待播放'), [queued, setQueued] = useState(0);
  const [progress, setProgress] = useState(0), [duration, setDuration] = useState(0);
  const [analyser, setAnalyser] = useState<AnalyserNode | null>(null);

  function audio() {
    if (!element.current) {
      const el = document.createElement('audio');
      el.dataset.companionPlayback = 'true';
      el.setAttribute('aria-hidden', 'true');
      el.style.display = 'none'; el.preload = 'metadata';
      document.body.appendChild(el); element.current = el;
    }
    return element.current;
  }
  async function prepareGraph() {
    const el = audio();
    if (!context.current) {
      context.current = new window.AudioContext();
      const node = context.current.createAnalyser(); node.fftSize = 128;
      source.current = context.current.createMediaElementSource(el);
      source.current.connect(node); node.connect(context.current.destination); setAnalyser(node);
    }
    if (context.current.state === 'suspended') await context.current.resume();
  }
  function cacheKey(item: QueueItem) { return item.group.signature + '\n' + item.text; }
  function remember(key: string, url: string) {
    cache.current.delete(key); cache.current.set(key, url);
    while (cache.current.size > 24) cache.current.delete(cache.current.keys().next().value!);
  }
  async function synthesize(item: QueueItem, token: number) {
    const abort = new AbortController(); requestAbort.current = abort;
    try {
      const result = await request<{ audio_url: string }>('/tts/synthesize', {
        method: 'POST', body: JSON.stringify({ text: item.text }), signal: abort.signal,
      });
      if (token !== generation.current || item.group.signature !== currentSignature.current) return null;
      const url = new URL(result.audio_url, window.location.origin);
      if (url.origin !== window.location.origin || !url.pathname.startsWith('/api/tts/audio/')) {
        throw new Error('语音服务返回了不可用的音频地址。');
      }
      remember(cacheKey(item), url.href); return url.href;
    } finally { if (requestAbort.current === abort) requestAbort.current = null; }
  }
  async function play(url: string, token: number) {
    const el = audio(); el.src = url; await prepareGraph();
    if (token !== generation.current) return;
    await new Promise<void>((resolve, reject) => {
      resolvePlayback.current = resolve;
      el.onended = () => resolve();
      el.onerror = () => reject(new PlaybackError('load', '音频加载失败，请重播或检查语音服务。'));
      el.ontimeupdate = () => setProgress(el.currentTime);
      el.onloadedmetadata = () => setDuration(Number.isFinite(el.duration) ? el.duration : 0);
      el.play().then(() => { if (token === generation.current) setPlaying(true); })
        .catch((failure: Error) => reject(failure.name === 'NotAllowedError'
          ? new PlaybackError('blocked', '浏览器暂未允许播放，请点击消息的播放按钮重试。')
          : new PlaybackError('load', '音频加载失败，请重播或检查语音服务。')));
    });
  }
  async function missing(url: string) {
    const abort = new AbortController(); requestAbort.current = abort;
    try {
      const response = await fetch(url, { signal: abort.signal, cache: 'no-store' });
      const absent = response.status === 404;
      await response.body?.cancel(); return absent;
    } finally { if (requestAbort.current === abort) requestAbort.current = null; }
  }
  async function drain() {
    if (working.current) return;
    working.current = true; const token = generation.current;
    try {
      while (queue.current.length && token === generation.current) {
        const item = queue.current.shift()!;
        if (item.group.signature !== currentSignature.current) continue;
        setQueued(queue.current.length); setBusy(true); setLabel(item.label);
        setError(''); setProgress(0); setDuration(0);
        try {
          const key = cacheKey(item), cached = cache.current.get(key);
          const url = cached || await synthesize(item, token);
          if (!url || token !== generation.current) break;
          remember(key, url); last.current = item.group;
          try { await play(url, token); }
          catch (failure) {
            // A removed cached file may be recreated once. Autoplay or network errors
            // never trigger another billed synthesis automatically.
            if (cached && failure instanceof PlaybackError && failure.kind === 'load'
                && token === generation.current && await missing(url)) {
              cache.current.delete(key);
              const replacement = await synthesize(item, token);
              if (replacement && token === generation.current) await play(replacement, token);
            } else throw failure;
          }
        } catch (failure) {
          if (token === generation.current && (failure as Error).name !== 'AbortError') setError((failure as Error).message);
        } finally { resolvePlayback.current = null; setPlaying(false); }
      }
    } finally {
      working.current = false; setBusy(false);
      if (queue.current.length) void drain();
    }
  }
  function enqueue(text: string, itemLabel = '叶瞬光的回应') {
    text = text.trim(); if (!text) return;
    if (!settings || settings.provider !== 'mimo' || settings.model !== 'mimo-v2.5-tts-voiceclone') {
      setError('请先在陪伴设置中保存小米参考声音克隆模型；不会回退到普通 TTS 或预置音色。'); return;
    }
    if (!settings.enabled || !settings.external_reference_enabled || !settings.reference_path) {
      setError('请先启用 TTS、选择本地 MP3 并允许合成时发送参考音频，然后保存配置。'); return;
    }
    if (text.length > 12000) { setError('这条回复较长，请复制所需段落；单次播放最多 12000 字。'); return; }
    void prepareGraph().catch(() => {});
    const chunks: string[] = [];
    while (text.length > 2800) {
      let end = Math.max(text.lastIndexOf('。', 2800), text.lastIndexOf('\n', 2800));
      end = end < 1000 ? 2800 : end + 1;
      chunks.push(text.slice(0, end)); text = text.slice(end);
    }
    if (text) chunks.push(text);
    const group: PlaybackGroup = { signature: currentSignature.current, clips: chunks.map((chunk, i) => ({
      text: chunk, label: chunks.length > 1 ? `${itemLabel}（${i + 1}/${chunks.length}）` : itemLabel,
    })) };
    queue.current.push(...group.clips.map(clip => ({ ...clip, group })));
    setQueued(queue.current.length); void drain();
  }
  function stop() {
    generation.current++; queue.current = []; setQueued(0);
    requestAbort.current?.abort(); requestAbort.current = null;
    const el = element.current;
    if (el) { el.pause(); el.removeAttribute('src'); el.load(); }
    resolvePlayback.current?.(); setPlaying(false); setBusy(false); setProgress(0);
  }
  function replay() {
    const group = last.current;
    if (!group || group.signature !== currentSignature.current) { setError('请先播放一条当前配置生成的语音。'); return; }
    stop(); void prepareGraph().catch(() => {});
    queue.current.push(...group.clips.map(clip => ({ ...clip, group })));
    setQueued(queue.current.length); setError(''); void drain();
  }
  function toggleMute() { setMuted(value => { const next = !value; audio().muted = next; return next; }); }
  useEffect(() => {
    if (previousSignature.current !== signature) {
      previousSignature.current = signature; stop(); cache.current.clear(); last.current = null;
    }
  }, [signature]);
  useEffect(() => () => {
    generation.current++; queue.current = []; cache.current.clear();
    requestAbort.current?.abort(); resolvePlayback.current?.();
    const el = element.current;
    if (el) { el.pause(); el.onended = null; el.onerror = null; el.ontimeupdate = null; el.onloadedmetadata = null; el.remove(); }
    element.current = null; void context.current?.close(); context.current = null; source.current = null;
  }, []);
  return { playing, busy, muted, error, label, queued, progress, duration, analyser, enqueue, stop, replay, toggleMute };
}
