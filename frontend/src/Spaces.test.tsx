import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { MemorySpace } from './Spaces';
import { request } from './api';

vi.mock('./api', async (original) => ({ ...(await original<typeof import('./api')>()), request: vi.fn() }));
afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});

it('edits the user profile in memory space without a manual conversation summary form', async () => {
  vi.mocked(request).mockImplementation((path) =>
    Promise.resolve(path === '/memories' ? [] : { nickname: '小师妹', city: '', age: null }),
  );
  render(<MemorySpace conversations={[]} active={null} />);
  const nickname = await screen.findByLabelText('小光对你的称呼');
  await waitFor(() => expect((nickname as HTMLInputElement).value).toBe('小师妹'));
  fireEvent.change(nickname, { target: { value: '小师弟' } });
  fireEvent.change(screen.getByLabelText('常住城市'), { target: { value: '南宁' } });
  fireEvent.change(screen.getByLabelText('年龄（选填）'), { target: { value: '23' } });
  fireEvent.click(screen.getByRole('button', { name: '保存个人资料' }));
  await waitFor(() =>
    expect(request).toHaveBeenCalledWith('/profile', {
      method: 'PATCH',
      body: JSON.stringify({ nickname: '小师弟', city: '南宁', age: 23 }),
    }),
  );
  expect(screen.queryByText('手动总结这段对话')).toBeNull();
});

it('shows background memory progress without asking the user to summarize a conversation', async () => {
  vi.mocked(request).mockImplementation((path) =>
    Promise.resolve(
      path === '/memories'
        ? []
        : path === '/memories/status'
          ? { queued: 2, running: 1, failed: 0, paused: 0, summaries: 3 }
          : { nickname: '小师妹', city: '', age: null },
    ),
  );
  render(<MemorySpace conversations={[]} active={null} />);
  expect(await screen.findByText('正在后台整理 · 1 个进行中，2 个排队')).toBeTruthy();
  expect(screen.getByText(/已整理 3 段对话摘要/)).toBeTruthy();
  expect(screen.queryByText('手动总结这段对话')).toBeNull();
});
