import { render, screen, within, cleanup, fireEvent } from '@testing-library/react';
import '@testing-library/jest-dom/vitest';
import { afterEach, it, expect, vi } from 'vitest';
import { request } from './api';
import { FileTasksProvider, MessageFileTasks } from './FileTasks';
import { useResourcePreview } from './PreviewContext';
vi.mock('./api', () => ({ request: vi.fn() }));
vi.mock('./PreviewContext', () => ({ useResourcePreview: vi.fn() }));
afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});
it('keeps a completed file conclusion at its initiating turn when later messages arrive', async () => {
  vi.mocked(request).mockResolvedValue([
    {
      id: 'task',
      title: '读取资料',
      status: 'complete',
      context: { source_message_id: 'first' },
      steps: [{ action: 'summarize', result: { abstract: '资料明确提到三个关键点。' } }],
    },
  ]);
  render(
    <FileTasksProvider conversationId="chat" onWork={vi.fn()}>
      <section aria-label="第一轮回复">
        <MessageFileTasks requestId="first" />
      </section>
      <section aria-label="后续回复">
        后续聊天
        <MessageFileTasks requestId="second" />
      </section>
    </FileTasksProvider>,
  );
  await screen.findByText('资料明确提到三个关键点。');
  expect(
    within(screen.getByRole('region', { name: '第一轮回复' })).getByText('资料明确提到三个关键点。'),
  ).toBeInTheDocument();
  expect(
    within(screen.getByRole('region', { name: '后续回复' })).queryByText('资料明确提到三个关键点。'),
  ).toBeNull();
});

it('opens the exact attachment for a legacy task when its source message still contains the reference', async () => {
  const open = vi.fn();
  vi.mocked(useResourcePreview).mockReturnValue(open);
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
      <MessageFileTasks
        taskIds={['legacy']}
        attachments={[
          { id: 'upload', workspace_id: 'files', path: 'copy.pdf', name: '原资料.pdf', bytes: 10 },
        ]}
      />
    </FileTasksProvider>,
  );
  fireEvent.click(await screen.findByText('预览资料'));
  expect(open).toHaveBeenCalledWith(
    { kind: 'attachment', id: 'upload', title: '原资料.pdf' },
    expect.anything(),
  );
});
