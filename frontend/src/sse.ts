/** Incremental SSE decoding, independent of React and fetch for protocol tests. */
export class SseDecoder {
  private buffer = '';
  private decoder = new TextDecoder();
  constructor(private emit: (name: string, data: Record<string, unknown>) => void) {}

  push(bytes?: Uint8Array, done = false) {
    this.buffer += this.decoder.decode(bytes, { stream: !done });
    let match: RegExpExecArray | null;
    while ((match = /\r?\n\r?\n/.exec(this.buffer))) {
      const frame = this.buffer.slice(0, match.index);
      this.buffer = this.buffer.slice(match.index + match[0].length);
      let name = 'message';
      const data: string[] = [];
      for (const line of frame.split(/\r?\n/)) {
        if (line.startsWith(':')) continue;
        const separator = line.indexOf(':');
        const field = separator < 0 ? line : line.slice(0, separator);
        const value = separator < 0 ? '' : line.slice(separator + 1).replace(/^ /, '');
        if (field === 'event') name = value;
        if (field === 'data') data.push(value);
      }
      if (data.length) {
        const parsed: unknown = JSON.parse(data.join('\n'));
        if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
          throw new Error('流式回复格式不正确。');
        }
        this.emit(name, parsed as Record<string, unknown>);
      }
    }
    if (this.buffer.length > 1_000_000) throw new Error('流式回复片段过大。');
    if (done && this.buffer.trim()) throw new Error('连接在回复片段完成前结束。');
  }
}
