import { render, screen, within, cleanup, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom/vitest';
import { afterEach, it, expect, vi } from 'vitest';
import { request } from './api';
import { AttachmentCard, FileTasksProvider, MessageFileTasks } from './FileTasks';
vi.mock('./api', () => ({ request: vi.fn() }));
afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});
it('refreshes a durable chat reply instead of repeating the result in a task card', async () => {
  vi.mocked(request).mockResolvedValue([
    {
      id: 'task',
      title: '读取资料',
      status: 'complete',
      context: { source_message_id: 'first', reply_message_id: 'file-result-task' },
      steps: [{ action: 'summarize', result: { abstract: '资料明确提到三个关键点。' } }],
    },
  ]);
  const onReply = vi.fn().mockResolvedValue(true);
  render(
    <FileTasksProvider conversationId="chat" onWork={vi.fn()} onReply={onReply}>
      <section aria-label="第一轮回复">
        <MessageFileTasks requestId="first" />
      </section>
      <section aria-label="后续回复">
        后续聊天
        <MessageFileTasks requestId="second" />
      </section>
    </FileTasksProvider>,
  );
  await waitFor(() => expect(onReply).toHaveBeenCalledOnce());
  expect(
    within(screen.getByRole('region', { name: '第一轮回复' })).queryByText('资料明确提到三个关键点。'),
  ).toBeNull();
  expect(screen.queryByText('读取资料')).toBeNull();
});

it('keeps the original attachment downloadable without legacy preview controls', async () => {
  vi.mocked(request).mockResolvedValue([
    {
      id: 'legacy',
      workspace_id: 'files',
      title: '旧阅读任务',
      status: 'complete',
      context: {},
      steps: [{ action: 'read_document', path: 'copy.pdf' }],
    },
  ]);
  render(
    <FileTasksProvider conversationId="chat" onWork={vi.fn()}>
      <AttachmentCard
        attachment={{ id: 'upload', workspace_id: 'files', path: 'copy.pdf', name: '原资料.pdf', bytes: 10 }}
      />
      <MessageFileTasks
        taskIds={['legacy']}
        attachments={[
          { id: 'upload', workspace_id: 'files', path: 'copy.pdf', name: '原资料.pdf', bytes: 10 },
        ]}
      />
    </FileTasksProvider>,
  );
  expect(await screen.findByRole('link', { name: '下载原件' })).toHaveAttribute(
    'href',
    '/api/work/files/upload',
  );
  expect(screen.queryByText('预览资料')).toBeNull();
  expect(screen.queryByText('状态与操作')).toBeNull();
});
