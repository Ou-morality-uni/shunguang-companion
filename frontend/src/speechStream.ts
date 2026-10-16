import { SseDecoder } from './sse';
import { httpError } from './httpError';

/** Bounded incremental text segmentation: punctuation, length, and an explicit timed flush. */
export class SpeechSegmenter {
  private buffer = '';
  constructor(private minimum = 0) {}
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
      const part = this.buffer.slice(0, end).trim();
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

/** Schedule PCM immediately, preserving sample boundaries even across odd network chunks. */
export class PcmPlayback {
  private next = 0;
  private carry: number | null = null;
  private nodes = new Set<AudioBufferSourceNode>();
  private waiters: Array<() => void> = [];
  seconds = 0;
  startedAt: number | null = null;
  constructor(
    private context: AudioContext,
    private output: AudioNode,
    private speed: number,
  ) {}
  push(bytes: Uint8Array) {
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
    const node = this.context.createBufferSource();
    node.buffer = buffer;
    node.playbackRate.value = this.speed;
    node.connect(this.output);
    const start = Math.max(this.next, this.context.currentTime + 0.035);
    this.startedAt ??= start;
    this.seconds += length / 24000;
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
    if (this.nodes.size) await new Promise<void>((resolve) => this.waiters.push(resolve));
  }
  stop() {
    for (const node of this.nodes) {
      node.onended = null;
      node.stop();
      node.disconnect();
    }
    this.nodes.clear();
    this.waiters.splice(0).forEach((resolve) => resolve());
  }
}
