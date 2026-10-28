import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { request, type FileTask } from './api';
import {
  ArtifactCard,
  AttachmentCard,
  ChatFileTasks,
  ContinueTask,
  DocumentMarkdown,
  OutputFolder,
  TaskDetails,
} from './FileTasks';
import { PreviewWorkspace } from './PreviewWorkspace';

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

it('shows the automatic project output folder without requiring a custom path', async () => {
  vi.mocked(request).mockResolvedValue({
    workspace: { id: 'out', enabled: true, path: 'C:/project/data/outputs' },
  });
  render(<OutputFolder />);
  await waitFor(() => expect(request).toHaveBeenCalledOnce());
  expect(request).not.toHaveBeenCalledWith('/work/output', expect.objectContaining({ method: 'POST' }));
  await screen.findByText('当前成果目录：C:/project/data/outputs');
  expect(screen.queryByLabelText('成果文件夹路径（本机已有文件夹）')).toBeNull();
  expect(screen.queryByText('更换成果文件夹')).toBeNull();
});

it('shows the conversation task and only resumes a workload pause after an explicit click', async () => {
  vi.mocked(request).mockImplementation((path) =>
    Promise.resolve(
      path.startsWith('/work/tasks?') ? [task] : path === '/work/tasks/t1' ? task : { workspace: null },
    ),
  );
  render(
    <PreviewWorkspace>
      <ChatFileTasks conversationId="c1" onSettings={vi.fn()} onWork={vi.fn()} />
    </PreviewWorkspace>,
  );
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

it('requires an explicit overwrite-and-backup action rather than generic task continuation', async () => {
  vi.mocked(request).mockResolvedValue({});
  render(
    <ContinueTask
      task={{
        ...task,
        context: { pause: { kind: 'overwrite', reason: '覆盖 C:/authorized/report.docx，原件将备份。' } },
      }}
      onChanged={vi.fn()}
    />,
  );
  expect(request).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: '确认覆盖并保留备份' }));
  await waitFor(() =>
    expect(request).toHaveBeenCalledWith('/work/tasks/t1/continue', {
      method: 'POST',
      body: JSON.stringify({ approved: true }),
    }),
  );
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

it('shows every saved Office artifact even if a later export failed and previews binary content safely', async () => {
  const fetchMock = vi.fn();
  vi.stubGlobal('fetch', fetchMock);
  vi.mocked(request).mockResolvedValue({
    blocks: [{ location: '正文第 1 块', text: '已保存的报告内容' }],
    warnings: [],
  });
  render(
    <ArtifactCard
      task={{
        ...task,
        status: 'failed',
        context: {
          artifacts: [
            { name: 'report.docx', path: '任务-t1/report.docx', workspace_id: 'out' },
            { name: 'report.pdf', path: '任务-t1/report.pdf', workspace_id: 'out' },
          ],
        },
      }}
    />,
  );
  const links = screen.getAllByRole('link', { name: '下载成果' });
  expect(links.map((link) => link.getAttribute('href'))).toEqual([
    '/api/work/artifacts/t1',
    '/api/work/artifacts/t1~1',
  ]);
  fireEvent.click(screen.getByRole('button', { name: '预览成果 report.docx' }));
  await screen.findByText('已保存的报告内容');
  expect(request).toHaveBeenCalledWith('/work/artifacts/t1/preview');
  expect(fetchMock).not.toHaveBeenCalled();
});

it('uses the continuous layout preview even when an attachment card is rendered standalone', async () => {
  vi.mocked(request).mockResolvedValue({ version: 'a'.repeat(64), name: '报告.docx', targets: [] });
  render(
    <AttachmentCard
      attachment={{ id: 'u1', name: '报告.docx', workspace_id: 'w1', path: 'copy.docx', bytes: 1024 }}
    />,
  );
  fireEvent.click(screen.getByRole('button', { name: '预览 报告.docx' }));
  await screen.findByLabelText('完整文档连续预览');
  expect(screen.queryByLabelText('预览页码')).toBeNull();
  expect(request).toHaveBeenCalledWith('/work/resources/attachment/u1/info', expect.anything());
});

it('retains readable code previews when an attachment card is rendered standalone', async () => {
  vi.mocked(request).mockResolvedValue({
    blocks: [{ location: '第 1 行', text: 'print("ready")' }],
    warnings: [],
  });
  render(
    <AttachmentCard
      attachment={{ id: 'code', name: 'example.py', workspace_id: 'files', path: 'copy.py', bytes: 14 }}
    />,
  );
  fireEvent.click(screen.getByRole('button', { name: '预览 example.py' }));
  expect(await screen.findByText('print("ready")')).toBeTruthy();
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

it('shows a compact artifact with an arrow download and a menu that reveals the exact saved version', async () => {
  vi.mocked(request).mockResolvedValue({ ok: true });
  render(
    <ArtifactCard
      task={{
        ...task,
        status: 'complete',
        context: {
          artifact: {
            name: 'result.xlsx',
            path: 'task/result.xlsx',
            workspace_id: 'out',
            sha256: 'a'.repeat(64),
          },
        },
      }}
    />,
  );
  expect(screen.getByRole('link', { name: '下载成果' }).querySelector('svg')).toBeTruthy();
  expect(screen.queryByText('本任务已保存的新副本，原文件保留。')).toBeNull();
  const menuButton = screen.getByRole('button', { name: '成果操作 result.xlsx' });
  fireEvent.pointerDown(menuButton, { button: 0, ctrlKey: false });
  fireEvent.click(await screen.findByRole('menuitem', { name: '查看位置' }));
  await waitFor(() =>
    expect(request).toHaveBeenCalledWith('/work/artifacts/t1/reveal', {
      method: 'POST',
      body: JSON.stringify({ version: 'a'.repeat(64) }),
    }),
  );
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
