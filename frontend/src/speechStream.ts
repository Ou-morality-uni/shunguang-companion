import { SseDecoder } from './sse';
import { httpError } from './httpError';

export function supportsLiveSpeech(model?: string) {
  return ['qwen-audio-3.1-tts-flash', 'qwen-audio-3.0-tts-flash', 'qwen-audio-3.0-tts-plus'].includes(
    model ?? '',
  );
}

/** Bounded incremental text segmentation: punctuation, length, and an explicit timed flush. */
export class SpeechSegmenter {
  private buffer = '';
  constructor(
    private minimum = 0,
    private preserveWhitespace = false,
  ) {}
  push(text: string, flush = false): string[] {
    this.buffer += text;
    const parts: string[] = [];
    while (this.buffer) {
      const pattern = /[。！？!?；;\n]|\.(?=\s)/g;
      if (this.minimum) pattern.lastIndex = Math.max(0, this.minimum - 1);
      const match = pattern.exec(this.buffer);
      let end = match ? match.index + 1 : 0;
      if (!end && this.buffer.length >= 180) end = 180;
      if (end > 180) end = 180;
      if (!end && flush) end = this.buffer.length;
      if (!end) break;
      // Do not split a UTF-16 surrogate pair at a length boundary.
      if (end < this.buffer.length && /[\uD800-\uDBFF]/.test(this.buffer[end - 1])) end--;
      const raw = this.buffer.slice(0, end);
      const part = this.preserveWhitespace ? raw : raw.trim();
      this.buffer = this.buffer.slice(end);
      if (part) parts.push(part);
    }
    return parts;
  }
}

export async function streamSpeech(text: string, signal: AbortSignal, onAudio: (pcm: Uint8Array) => void) {
  const response = await fetch('/api/tts/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text }),
    signal,
  });
  if (!response.ok) {
    throw await httpError(response, '语音流连接失败。');
  }
  if (!response.body) throw new Error('浏览器无法读取语音流。');
  let result = '',
    completed = false,
    size = 0;
  const decoder = new SseDecoder((kind, data) => {
    if (completed) throw new Error('语音流结束后仍收到数据。');
    if (kind === 'error') throw new Error(String(data.message || '语音生成失败。'));
    if (kind === 'audio') {
      if (data.sample_rate !== 24000 || typeof data.pcm !== 'string') throw new Error('语音格式不正确。');
      const raw = atob(data.pcm);
      size += raw.length;
      if (size > 20_000_000) throw new Error('语音响应过大。');
      onAudio(Uint8Array.from(raw, (char) => char.charCodeAt(0)));
    }
    if (kind === 'done') {
      if (typeof data.audio_url !== 'string' || !size) throw new Error('语音流没有有效音频。');
      result = data.audio_url;
      completed = true;
    }
  });
  const reader = response.body.getReader();
  try {
    while (true) {
      const { value, done } = await reader.read();
      decoder.push(value, done);
      if (done) break;
    }
    if (!completed) throw new Error('语音连接提前结束，请重新播放。');
    return result;
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}

/** A single duplex task; never retries a potentially billed stream automatically. */
export function liveSpeech(signal: AbortSignal, onAudio: (pcm: Uint8Array) => void) {
  const url = new URL('/api/tts/live', window.location.href);
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
  const socket = new WebSocket(url);
  socket.binaryType = 'arraybuffer';
  const pending: string[] = [];
  let closed = false,
    finishing = false,
    size = 0;
  const connectionTimer = setTimeout(() => end(new Error('连续语音连接超时，请检查服务。')), 15000);
  let resolve!: (url: string) => void, reject!: (error: Error) => void;
  const promise = new Promise<string>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  function end(error?: Error, result = '') {
    if (closed) return;
    closed = true;
    clearTimeout(connectionTimer);
    signal.removeEventListener('abort', abort);
    socket.close();
    if (error) reject(error);
    else resolve(result);
  }
  function abort() {
    end(new DOMException('语音已停止。', 'AbortError'));
  }
  function send(value: object) {
    if (closed) return;
    const raw = JSON.stringify(value);
    if (socket.readyState === WebSocket.OPEN) socket.send(raw);
    else pending.push(raw);
  }
  socket.onopen = () => {
    clearTimeout(connectionTimer);
    if (closed) {
      socket.close();
      return;
    }
    pending.splice(0).forEach((raw) => socket.send(raw));
  };
  socket.onmessage = (event) => {
    if (closed) return;
    try {
      if (event.data instanceof ArrayBuffer) {
        size += event.data.byteLength;
        if (size > 20_000_000) throw new Error('语音响应过大。');
        onAudio(new Uint8Array(event.data));
      } else {
        const data = JSON.parse(event.data);
        if (data.type === 'error') throw new Error(String(data.message || '语音生成失败。'));
        if (data.type !== 'done' || !finishing || !size || typeof data.audio_url !== 'string')
          throw new Error('连续语音未完整结束。');
        end(undefined, data.audio_url);
      }
    } catch (failure) {
      end(failure as Error);
    }
  };
  socket.onerror = () => end(new Error('连续语音连接失败，请检查服务或局域网登录状态。'));
  socket.onclose = () => end(new Error('连续语音提前中断，请重新播放。'));
  signal.addEventListener('abort', abort, { once: true });
  if (signal.aborted) abort();
  return {
    promise,
    push: (text: string) => {
      if (!finishing) send({ type: 'text', text });
    },
    finish: () => {
      if (!finishing) {
        finishing = true;
        send({ type: 'finish' });
      }
    },
  };
}

/** Preserve sample boundaries; duplex playback adds a bounded jitter buffer. */
export class PcmPlayback {
  private next = 0;
  private carry: number | null = null;
  private nodes = new Set<AudioBufferSourceNode>();
  private waiters: Array<() => void> = [];
  private pending: AudioBuffer[] = [];
  private buffered = 0;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private stopped = false;
  seconds = 0;
  startedAt: number | null = null;
  constructor(
    private context: AudioContext,
    private output: AudioNode,
    private speed: number,
    private bufferSeconds = 0,
  ) {}
  push(bytes: Uint8Array) {
    if (this.stopped) return;
    if (this.carry !== null) {
      const joined = new Uint8Array(bytes.length + 1);
      joined[0] = this.carry;
      joined.set(bytes, 1);
      bytes = joined;
      this.carry = null;
    }
    if (bytes.length % 2) this.carry = bytes[bytes.length - 1];
    const length = Math.floor(bytes.length / 2);
    if (!length) return;
    const buffer = this.context.createBuffer(1, length, 24000);
    const samples = buffer.getChannelData(0);
    const view = new DataView(bytes.buffer, bytes.byteOffset, length * 2);
    for (let i = 0; i < length; i++) samples[i] = view.getInt16(i * 2, true) / 32768;
    this.seconds += length / 24000;
    this.pending.push(buffer);
    this.buffered += buffer.duration / this.speed;
    if (this.next > this.context.currentTime || this.buffered >= this.bufferSeconds) this.flush();
    else if (!this.timer) this.timer = setTimeout(() => this.flush(), this.bufferSeconds * 1000);
  }
  private flush() {
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    this.buffered = 0;
    for (const buffer of this.pending.splice(0)) this.schedule(buffer);
  }
  private schedule(buffer: AudioBuffer) {
    const node = this.context.createBufferSource();
    node.buffer = buffer;
    node.playbackRate.value = this.speed;
    node.connect(this.output);
    const start = this.next > this.context.currentTime ? this.next : this.context.currentTime + 0.035;
    this.startedAt ??= start;
    this.next = start + buffer.duration / this.speed;
    this.nodes.add(node);
    node.onended = () => {
      node.disconnect();
      this.nodes.delete(node);
      if (!this.nodes.size) this.waiters.splice(0).forEach((resolve) => resolve());
    };
    node.start(start);
  }
  async finish() {
    if (this.carry !== null) throw new Error('PCM 音频不完整。');
    this.flush();
    if (this.nodes.size) await new Promise<void>((resolve) => this.waiters.push(resolve));
  }
  stop() {
    this.stopped = true;
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    this.pending = [];
    for (const node of this.nodes) {
      node.onended = null;
      node.stop();
      node.disconnect();
    }
    this.nodes.clear();
    this.waiters.splice(0).forEach((resolve) => resolve());
  }
}
