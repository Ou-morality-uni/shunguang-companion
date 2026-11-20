import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { request, type FileTask } from './api';
import { ChatFileTasks, DocumentMarkdown, TaskDetails } from './FileTasks';

vi.mock('./api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./api')>()),
  request: vi.fn(),
}));
afterEach(() => {
  cleanup();
  vi.resetAllMocks();
  vi.unstubAllGlobals();
  sessionStorage.clear();
});

const task: FileTask = {
  id: 't1',
  workspace_id: 'w1',
  title: '阅读资料',
  status: 'waiting_limit',
  steps: [],
  origin: 'chat',
  conversation_id: 'c1',
  error: '',
  can_restore: false,
  can_retry_summary: false,
  created_at: '2026-10-23',
  updated_at: '2026-10-23',
  context: { pause: { reason: '已读范围保留，等待继续。' } },
};

it('only retries the completed reading after an explicit summary retry click', async () => {
  vi.mocked(request).mockResolvedValue({});
  const onChanged = vi.fn().mockResolvedValue(undefined);
  render(
    <TaskDetails
      task={{ ...task, status: 'failed', error: '模型响应超时', can_retry_summary: true }}
      enter={false}
      onChanged={onChanged}
      onSettings={vi.fn()}
      attachments={[]}
    />,
  );
  expect(screen.getByText('这次没读完，可以再试一次。')).toBeTruthy();
  expect(request).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: '再试一次' }));
  await waitFor(() =>
    expect(request).toHaveBeenCalledWith('/work/tasks/t1/retry-summary', {
      method: 'POST',
      body: JSON.stringify({ extend_timeout: true }),
    }),
  );
  expect(onChanged).toHaveBeenCalledOnce();
});

it('shows the conversation task and only resumes a workload pause after an explicit click', async () => {
  vi.mocked(request).mockImplementation((path) =>
    Promise.resolve(
      path.startsWith('/work/tasks?') ? [task] : path === '/work/tasks/t1' ? task : { workspace: null },
    ),
  );
  render(<ChatFileTasks conversationId="c1" onSettings={vi.fn()} onWork={vi.fn()} />);
  expect(screen.queryByRole('region', { name: '文件预览' })).toBeNull();
  expect(screen.queryByText('状态与操作')).toBeNull();
  expect(screen.queryByText('预览资料')).toBeNull();
  await screen.findByRole('group', { name: '任务继续确认' });
  expect(request).not.toHaveBeenCalledWith('/work/tasks/t1/continue', expect.anything());
  fireEvent.click(screen.getByRole('button', { name: '继续下一轮处理' }));
  await waitFor(() =>
    expect(request).toHaveBeenCalledWith('/work/tasks/t1/continue', {
      method: 'POST',
      body: JSON.stringify({ approved: true }),
    }),
  );
  expect(request).toHaveBeenCalledWith('/work/tasks?conversation_id=c1&compact=true', expect.anything());
});

it('does not load document-supplied remote images or execute raw HTML', () => {
  render(
    <DocumentMarkdown
      text={
        '![tracking](https://example.com/private.png)\n\n<script>alert(1)</script>\n\n```sh\nrm -rf test\n```'
      }
    />,
  );
  expect(document.querySelector('img')).toBeNull();
  expect(document.querySelector('script')).toBeNull();
  expect(document.querySelector('pre code')?.textContent).toContain('rm -rf test');
});

it('keeps a short retry in chat and hides internal task titles, source extracts and management links', async () => {
  const failed = {
    ...task,
    title: '内部阅读任务',
    status: 'failed' as const,
    error: '模型响应超时，请调整超时时间',
    can_retry_summary: true,
    steps: [
      {
        action: 'read_document',
        path: 'private.pdf',
        state: 'complete',
        result: { blocks: [{ location: '第1页', text: '提取原文不应显示' }] },
      },
    ],
  };
  vi.mocked(request).mockImplementation(async (path) => (path.startsWith('/work/tasks?') ? [failed] : {}));
  render(<ChatFileTasks conversationId="c1" onSettings={vi.fn()} onWork={vi.fn()} />);
  await screen.findByRole('button', { name: '再试一次' });
  expect(screen.queryByText('内部阅读任务')).toBeNull();
  expect(screen.queryByText('提取原文不应显示')).toBeNull();
  expect(screen.queryByText('状态与操作')).toBeNull();
  expect(screen.queryByText('预览资料')).toBeNull();
  expect(screen.queryByText(/调整超时时间/)).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: '再试一次' }));
  await waitFor(() =>
    expect(request).toHaveBeenCalledWith('/work/tasks/t1/retry-summary', {
      method: 'POST',
      body: JSON.stringify({ extend_timeout: true }),
    }),
  );
});
