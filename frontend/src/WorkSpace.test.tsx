import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { FilePermissions } from './WorkSpace';
import { TaskDetails } from './FileTasks';
import { request, type FileTask } from './api';

vi.mock('./api', () => ({ request: vi.fn() }));
afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});

const workspace = { id: 'w1', path: 'D:\\work', enabled: true, created_at: '2026-10-22T00:00:00Z' };
const pending: FileTask = {
  origin: 'workbench',
  id: 't1',
  workspace_id: 'w1',
  title: '删除旧文件',
  status: 'waiting_approval',
  error: '',
  created_at: '2026-10-22T00:00:00Z',
  updated_at: '2026-10-22T00:00:00Z',
  can_restore: false,
  steps: [{ action: 'delete', path: 'old.txt', state: 'pending' }],
};

it('shows exact deletion targets and only authorizes after an explicit click', async () => {
  vi.mocked(request).mockImplementation((path) =>
    Promise.resolve(path === '/work/workspaces' ? [workspace] : path === '/work/tasks' ? [pending] : {}),
  );
  render(
    <TaskDetails task={pending} enter={false} onChanged={vi.fn()} onSettings={vi.fn()} attachments={[]} />,
  );
  await screen.findByRole('group', { name: '删除授权' });
  expect(screen.getByText('delete：old.txt')).toBeTruthy();
  expect(request).not.toHaveBeenCalledWith('/work/tasks/t1/approval', expect.anything());
  fireEvent.click(screen.getByRole('button', { name: '同意执行此任务（含删除）' }));
  await waitFor(() =>
    expect(request).toHaveBeenCalledWith('/work/tasks/t1/approval', {
      method: 'POST',
      body: JSON.stringify({ approved: true }),
    }),
  );
});

it('grants the entered folder through on-demand file permissions', async () => {
  let granted = false;
  vi.mocked(request).mockImplementation((path, options) => {
    if (path === '/work/workspaces' && options?.method === 'POST') {
      granted = true;
      return Promise.resolve(workspace);
    }
    return Promise.resolve(path === '/work/workspaces' ? (granted ? [workspace] : []) : []);
  });
  render(<FilePermissions />);
  fireEvent.change(screen.getByLabelText('本机文件夹完整路径'), { target: { value: 'D:\\work' } });
  fireEvent.click(screen.getByRole('button', { name: '授权此文件夹' }));
  await screen.findByText('工作文件夹已授权。');
  expect(request).toHaveBeenCalledWith('/work/workspaces', {
    method: 'POST',
    body: JSON.stringify({ path: 'D:\\work' }),
  });
});

it('offers recovery only for task records that can be restored', async () => {
  const edited: FileTask = {
    ...pending,
    status: 'complete',
    can_restore: true,
    steps: [{ action: 'write', path: 'note.txt', state: 'applied' }],
  };
  vi.mocked(request).mockImplementation((path) =>
    Promise.resolve(path === '/work/workspaces' ? [workspace] : [edited]),
  );
  render(
    <TaskDetails task={edited} enter={false} onChanged={vi.fn()} onSettings={vi.fn()} attachments={[]} />,
  );
  fireEvent.click(await screen.findByRole('button', { name: '恢复本次文件修改' }));
  await waitFor(() => expect(request).toHaveBeenCalledWith('/work/tasks/t1/restore', { method: 'POST' }));
});
