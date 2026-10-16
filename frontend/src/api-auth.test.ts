import { afterEach, expect, it, vi } from 'vitest';
import { request, streamChat } from './api';
import { streamSpeech } from './speechStream';

afterEach(() => vi.unstubAllGlobals());

const transports = [
  ['voice management', () => request('/tts/voices')],
  ['chat', () => streamChat(null, '你好', new AbortController().signal, vi.fn())],
  ['speech', () => streamSpeech('你好', new AbortController().signal, vi.fn())],
] as const;

it.each(transports)(
  '%s shows provider authentication errors without requesting LAN login',
  async (_, send) => {
    const auth = vi.fn();
    window.addEventListener('shunguang-auth-required', auth);
    try {
      const message = '语音服务鉴权或权限失败，请检查密钥及模型权限。';
      vi.stubGlobal(
        'fetch',
        vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: message }), { status: 401 })),
      );
      await expect(send()).rejects.toThrow(message);
      expect(auth).not.toHaveBeenCalled();
    } finally {
      window.removeEventListener('shunguang-auth-required', auth);
    }
  },
);

it.each(transports)('%s requests login when the local LAN session is missing or expired', async (_, send) => {
  const auth = vi.fn();
  window.addEventListener('shunguang-auth-required', auth);
  try {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: '请先输入局域网访问口令。', code: 'lan_auth_required' }), {
          status: 401,
        }),
      ),
    );
    await expect(send()).rejects.toThrow('请先输入局域网访问口令。');
    expect(auth).toHaveBeenCalledOnce();
  } finally {
    window.removeEventListener('shunguang-auth-required', auth);
  }
});
