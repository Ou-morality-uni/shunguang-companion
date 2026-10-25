import { afterEach, expect, it, vi } from 'vitest';
import { createWorker } from 'tesseract.js';
import { recognizePage } from './localOcr';

vi.mock('tesseract.js', () => ({ createWorker: vi.fn() }));
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
it('cancels in-flight recognition and releases the worker without leaving a pending result', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('image')));
  const close = vi.fn();
  vi.stubGlobal('createImageBitmap', vi.fn().mockResolvedValue({ width: 100, height: 100, close }));
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({
    translate: vi.fn(),
    rotate: vi.fn(),
    drawImage: vi.fn(),
  } as unknown as CanvasRenderingContext2D);
  let started!: () => void;
  const running = new Promise<void>((resolve) => {
    started = resolve;
  });
  const terminate = vi.fn().mockResolvedValue(undefined);
  vi.mocked(createWorker).mockResolvedValue({
    recognize: vi.fn(() => {
      started();
      return new Promise(() => {});
    }),
    terminate,
  } as unknown as Awaited<ReturnType<typeof createWorker>>);
  const abort = new AbortController();
  const result = recognizePage('/same-origin-image', abort.signal, vi.fn());
  const assertion = expect(result).rejects.toMatchObject({ name: 'AbortError' });
  await running;
  abort.abort();
  await assertion;
  expect(terminate).toHaveBeenCalled();
  expect(close).toHaveBeenCalledOnce();
});
