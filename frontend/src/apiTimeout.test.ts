import { afterEach, expect, test, vi } from 'vitest';
import { request } from './api';

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

test('ordinary requests report a bounded timeout instead of hanging', async () => {
  vi.useFakeTimers();
  vi.stubGlobal(
    'fetch',
    vi.fn(
      (_url, options) =>
        new Promise((_resolve, reject) => {
          options.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')));
        }),
    ),
  );
  const failure = expect(request('/health')).rejects.toThrow('服务无响应');
  await vi.advanceTimersByTimeAsync(15000);
  await failure;
});
