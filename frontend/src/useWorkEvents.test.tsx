import { act, cleanup, renderHook } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { request } from './api';
import { useWorkEvents } from './useWorkEvents';
import type { AudioController } from './useAudioQueue';

vi.mock('./api', () => ({ request: vi.fn() }));

it('only announces a short completion cue and never automatically fetches or reads the full summary', async () => {
  vi.useFakeTimers();
  const enqueueWork = vi.fn();
  const audio = { enqueueWork } as unknown as AudioController;
  vi.mocked(request).mockImplementation((path) =>
    Promise.resolve(
      path === '/work/events'
        ? { cursor: 0, events: [] }
        : path.startsWith('/work/tasks/')
          ? {
              origin: 'chat',
              status: 'complete',
              steps: [{ action: 'summarize', result: { summary: 'already in chat' } }],
            }
          : {
              cursor: 1,
              events: [
                {
                  seq: 1,
                  task_id: 't1',
                  kind: 'complete',
                  text: '处理完啦。',
                  created_at: new Date().toISOString(),
                },
              ],
            },
    ),
  );
  renderHook(() => useWorkEvents(true, audio));
  await act(async () => {});
  await act(async () => vi.advanceTimersByTimeAsync(1000));
  expect(enqueueWork).toHaveBeenCalledTimes(1);
  expect(enqueueWork.mock.calls[0][0].kind).toBe('complete');
  expect(request).not.toHaveBeenCalledWith('/work/tasks/t1', expect.anything());
});
afterEach(() => {
  cleanup();
  vi.resetAllMocks();
  vi.useRealTimers();
});

it('never starts reading a full summary after subsequent polling', async () => {
  vi.useFakeTimers();
  const enqueueWork = vi.fn(),
    audio = { enqueueWork } as unknown as AudioController;
  const event = {
    seq: 1,
    task_id: 't1',
    kind: 'complete',
    text: '处理完成。',
    created_at: new Date().toISOString(),
  };
  vi.mocked(request).mockImplementation((path) =>
    Promise.resolve(
      path === '/work/events'
        ? { cursor: 0, events: [] }
        : path.startsWith('/work/tasks/')
          ? {
              status: 'complete',
              origin: 'chat',
              steps: [{ action: 'summarize', result: { summary: '后台整理结果。' } }],
            }
          : { cursor: 1, events: [event] },
    ),
  );
  const { rerender } = renderHook(() => useWorkEvents(true, audio));
  await act(async () => {});
  await act(async () => vi.advanceTimersByTimeAsync(1000));
  expect(enqueueWork).toHaveBeenCalledTimes(1);
  expect(enqueueWork.mock.calls[0][0].kind).toBe('complete');
  rerender();
  await act(async () => vi.advanceTimersByTimeAsync(1000));
  expect(enqueueWork).toHaveBeenCalledTimes(1);
  expect(request).not.toHaveBeenCalledWith('/work/tasks/t1', expect.anything());
});

it('starts at the cursor, drops obsolete progress and deduplicates repeated events', async () => {
  vi.useFakeTimers();
  const enqueueWork = vi.fn(),
    audio = { enqueueWork } as unknown as AudioController;
  const base = { task_id: 't1', text: '完成了。', created_at: new Date().toISOString() };
  vi.mocked(request).mockImplementation((path) =>
    Promise.resolve(
      path === '/work/events'
        ? { cursor: 10, events: [] }
        : path.startsWith('/work/tasks/')
          ? { status: 'complete', steps: [] }
          : {
              cursor: 12,
              events: [
                { ...base, seq: 11, kind: 'start' },
                { ...base, seq: 12, kind: 'complete' },
              ],
            },
    ),
  );
  renderHook(() => useWorkEvents(true, audio));
  await act(async () => {});
  expect(enqueueWork).not.toHaveBeenCalled();
  await act(async () => vi.advanceTimersByTimeAsync(1000));
  expect(enqueueWork).toHaveBeenCalledTimes(1);
  expect(enqueueWork.mock.calls[0][0].kind).toBe('complete');
  await act(async () => vi.advanceTimersByTimeAsync(1000));
  expect(enqueueWork).toHaveBeenCalledTimes(1);
});
