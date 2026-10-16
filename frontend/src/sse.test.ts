import { describe, expect, it, vi, afterEach } from 'vitest';
import { SseDecoder } from './sse';
import { request, streamChat } from './api';

afterEach(() => vi.unstubAllGlobals());

describe('stream transport', () => {
  it('decodes Chinese UTF-8 split at every byte, CRLF, comments and multiple frames', () => {
    const emit = vi.fn();
    const decoder = new SseDecoder(emit);
    const bytes = new TextEncoder().encode(
      ': ping\r\nevent:delta\r\ndata:{"text":"你好"}\r\n\r\nevent: done\ndata: {"status":"complete"}\n\n',
    );
    for (const byte of bytes) decoder.push(new Uint8Array([byte]));
    decoder.push(undefined, true);
    expect(emit.mock.calls).toEqual([
      ['delta', { text: '你好' }],
      ['done', { status: 'complete' }],
    ]);
  });
  it('supports multiline data and rejects malformed/truncated frames', () => {
    const emit = vi.fn();
    const decoder = new SseDecoder(emit);
    decoder.push(new TextEncoder().encode('event: delta\ndata: {\ndata: "text":"ok"}\n\n'));
    expect(emit).toHaveBeenCalledWith('delta', { text: 'ok' });
    expect(() => decoder.push(new TextEncoder().encode('data: {broken}\n\n'))).toThrow();
    expect(() => new SseDecoder(emit).push(new TextEncoder().encode('data: {}'), true)).toThrow();
  });
  it('requires a terminal event even when HTTP status is successful', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(new Response('event: delta\ndata: {"text":"部分"}\n\n')),
    );
    await expect(streamChat(null, 'hello', new AbortController().signal, vi.fn())).rejects.toThrow(
      '提前结束',
    );
  });
  it('handles no-content deletion and propagates auth failure', async () => {
    const auth = vi.fn();
    window.addEventListener('shunguang-auth-required', auth);
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValueOnce(new Response(null, { status: 204 }))
        .mockResolvedValueOnce(
          new Response('{"detail":"请登录","code":"lan_auth_required"}', { status: 401 }),
        ),
    );
    await expect(request('/conversations/id', { method: 'DELETE' })).resolves.toBeUndefined();
    await expect(request('/settings')).rejects.toThrow('请登录');
    expect(auth).toHaveBeenCalledOnce();
    window.removeEventListener('shunguang-auth-required', auth);
  });
});
