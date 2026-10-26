import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import '@testing-library/jest-dom/vitest';
import { afterEach, expect, it, vi } from 'vitest';
import { request } from './api';
import { UpdateSettings } from './UpdateSettings';

vi.mock('./api', () => ({ request: vi.fn() }));
afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});

const newer = {
  current_version: '0.6.3',
  latest_version: '0.6.10',
  status: 'available',
  published_at: '2026-10-26',
  summary: '新增功能与修复。',
  release_notes_url:
    'https://github.com/Ou-morality-uni/shunguang-companion/blob/main/versions/0.6.10/README.md',
  checked_at: '2026-10-26T08:00:00Z',
  cached: false,
};

it('checks only on click and shows the new version and manual update instructions', async () => {
  vi.mocked(request).mockResolvedValue(newer);
  render(<UpdateSettings currentVersion="0.6.3" onRefreshVersion={vi.fn()} />);
  expect(screen.getByText('当前版本：v0.6.3')).toBeInTheDocument();
  expect(request).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: '检查更新' }));
  expect(await screen.findByText('发现新版本 v0.6.10')).toBeInTheDocument();
  expect(request).toHaveBeenCalledWith('/updates/check', expect.objectContaining({ method: 'POST' }));
  expect(screen.getByRole('link', { name: '查看更新说明' })).toHaveAttribute('href', newer.release_notes_url);
  expect(screen.getByText(/Install.bat/)).toBeInTheDocument();
});

it('disables duplicate checks while waiting and allows retry after a network error', async () => {
  let reject!: (error: Error) => void;
  vi.mocked(request)
    .mockImplementationOnce(
      () =>
        new Promise((_, fail) => {
          reject = fail;
        }),
    )
    .mockResolvedValueOnce({ ...newer, status: 'current', latest_version: '0.6.3', cached: true });
  render(<UpdateSettings currentVersion="0.6.3" onRefreshVersion={vi.fn()} />);
  fireEvent.click(screen.getByRole('button', { name: '检查更新' }));
  expect(screen.getByRole('button', { name: '正在检查更新…' })).toBeDisabled();
  await act(async () => reject(new Error('检查更新超时，请检查网络后重试。')));
  expect(await screen.findByRole('alert')).toHaveTextContent('检查更新超时');
  expect(screen.queryByText(/已是最新/)).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: '检查更新' }));
  expect(await screen.findByText('当前已是最新版本 v0.6.3')).toBeInTheDocument();
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  expect(screen.getByText(/缓存结果/)).toBeInTheDocument();
});

it('clears a previous success when a new check fails', async () => {
  vi.mocked(request).mockResolvedValueOnce(newer).mockRejectedValueOnce(new Error('无法连接更新服务'));
  render(<UpdateSettings currentVersion="0.6.3" onRefreshVersion={vi.fn()} />);
  fireEvent.click(screen.getByRole('button', { name: '检查更新' }));
  await screen.findByText('发现新版本 v0.6.10');
  fireEvent.click(screen.getByRole('button', { name: '检查更新' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('无法连接更新服务');
  expect(screen.queryByRole('link', { name: '查看更新说明' })).not.toBeInTheDocument();
});

it('shows an ahead version without suggesting downgrade and can reread an unknown local version', async () => {
  const reread = vi.fn().mockResolvedValue(undefined);
  vi.mocked(request).mockResolvedValue({ ...newer, status: 'ahead', latest_version: '0.6.2' });
  render(<UpdateSettings currentVersion={null} onRefreshVersion={reread} />);
  expect(screen.getByText('当前版本：版本未知')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: '重新读取版本' }));
  expect(reread).toHaveBeenCalledOnce();
  expect(request).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: '检查更新' }));
  expect(await screen.findByText('本机版本高于公开版本 v0.6.2，无需降级。')).toBeInTheDocument();
  expect(screen.queryByRole('link', { name: '查看更新说明' })).not.toBeInTheDocument();
});

it('renders the release summary as text and aborts a pending check when leaving', async () => {
  vi.mocked(request).mockResolvedValueOnce({ ...newer, summary: '<script>window.bad = true</script>' });
  const view = render(<UpdateSettings currentVersion="0.6.3" onRefreshVersion={vi.fn()} />);
  fireEvent.click(screen.getByRole('button', { name: '检查更新' }));
  expect(await screen.findByText('<script>window.bad = true</script>')).toBeInTheDocument();
  expect(view.container.querySelector('script')).toBeNull();
  vi.mocked(request).mockImplementationOnce(() => new Promise(() => {}));
  fireEvent.click(screen.getByRole('button', { name: '检查更新' }));
  const options = vi.mocked(request).mock.calls.at(-1)![1];
  view.unmount();
  expect(options?.signal?.aborted).toBe(true);
});
