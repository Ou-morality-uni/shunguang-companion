import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { request, type FileTask } from './api';
import { ArtifactCard, AttachmentCard, ChatFileTasks, DocumentMarkdown, OutputFolder } from './FileTasks';

vi.mock('./api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./api')>()),
  request: vi.fn(),
}));
afterEach(() => {
  cleanup();
  vi.resetAllMocks();
  vi.unstubAllGlobals();
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
  created_at: '2026-10-23',
  updated_at: '2026-10-23',
  context: { pause: { reason: '已读范围保留，等待继续。' } },
};

it('requires an explicit folder grant and remembers the selected output location', async () => {
  vi.mocked(request).mockImplementation((path, options) =>
    Promise.resolve({
      workspace: options?.method === 'POST' ? { id: 'out', enabled: true, path: 'D:\\成果' } : null,
    }),
  );
  render(<OutputFolder />);
  await waitFor(() => expect(request).toHaveBeenCalledOnce());
  expect(request).not.toHaveBeenCalledWith('/work/output', expect.objectContaining({ method: 'POST' }));
  fireEvent.change(screen.getByLabelText('成果文件夹路径（本机已有文件夹）'), {
    target: { value: 'D:\\成果' },
  });
  fireEvent.click(screen.getByRole('button', { name: '授权并设为成果目录' }));
  await screen.findByText('当前成果目录：D:\\成果');
  expect(request).toHaveBeenCalledWith('/work/output', {
    method: 'POST',
    body: JSON.stringify({ path: 'D:\\成果' }),
  });
});

it('shows the conversation task and only resumes a workload pause after an explicit click', async () => {
  vi.mocked(request).mockImplementation((path) =>
    Promise.resolve(path.startsWith('/work/tasks?') ? [task] : { workspace: null }),
  );
  render(<ChatFileTasks conversationId="c1" onSettings={vi.fn()} onWork={vi.fn()} />);
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

it('previews the actual saved Markdown file and exposes a download without another model call', async () => {
  const fetchMock = vi.fn().mockResolvedValue(new Response('# 保存的成品\n\n真实内容。'));
  vi.stubGlobal('fetch', fetchMock);
  render(
    <ArtifactCard
      task={{
        ...task,
        status: 'complete',
        context: { artifact: { name: '资料总结.md', path: '任务-t1/资料总结.md', workspace_id: 'out' } },
      }}
    />,
  );
  expect(screen.getByRole('link', { name: '下载总结' }).getAttribute('href')).toBe('/api/work/artifacts/t1');
  fireEvent.click(screen.getByRole('button', { name: '预览总结文件' }));
  await screen.findByRole('heading', { name: '保存的成品' });
  expect(fetchMock).toHaveBeenCalledWith('/api/work/artifacts/t1');
  expect(request).not.toHaveBeenCalled();
});

it('renders Office content and source locations through the local preview route', async () => {
  vi.mocked(request).mockResolvedValue({
    blocks: [{ location: '正文第 8 块', text: '原文内容' }],
    warnings: [],
  });
  render(
    <AttachmentCard
      attachment={{ id: 'u1', name: '报告.docx', workspace_id: 'w1', path: 'copy.docx', bytes: 1024 }}
    />,
  );
  fireEvent.click(screen.getByRole('button', { name: '预览 报告.docx' }));
  await screen.findByText('正文第 8 块');
  expect(screen.getByText('原文内容')).toBeTruthy();
  expect(request).toHaveBeenCalledWith('/work/files/u1/preview?start=1');
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
