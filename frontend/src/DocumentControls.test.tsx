import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { request } from './api';
import { UploadDocuments, VisionApproval } from './DocumentControls';

vi.mock('./api', () => ({ request: vi.fn() }));
afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});

it('uploads a local copy and prepares document reading without silently starting recognition', async () => {
  const onUploaded = vi.fn();
  const workspace = { id: 'attachments', path: 'local attachments', enabled: true };
  vi.mocked(request).mockResolvedValue({ workspace, path: 'copy-example.pdf' });
  render(<UploadDocuments onUploaded={onUploaded} />);
  const file = new File(['pdf sample'], 'example.pdf', { type: 'application/pdf' });
  fireEvent.change(screen.getByLabelText('选择上传文件'), { target: { files: [file] } });
  await waitFor(() =>
    expect(onUploaded).toHaveBeenCalledWith(workspace, [
      { action: 'read_document', path: 'copy-example.pdf', start: 1, limit: 20 },
    ]),
  );
  expect(request).toHaveBeenCalledTimes(1);
  expect(request).toHaveBeenCalledWith('/work/upload?name=example.pdf', {
    method: 'POST',
    headers: { 'Content-Type': 'application/octet-stream' },
    body: file,
  });
});

it('shows the destination, file, locations and cost before binding a selected vision service', async () => {
  const onChanged = vi.fn().mockResolvedValue(undefined);
  const profile = {
    id: 'v1',
    signature: 'sig',
    model: 'visual',
    base_url: 'https://vision.example/v1',
    service: 'vision.example',
    external: true,
  };
  vi.mocked(request).mockImplementation((path) =>
    Promise.resolve(path === '/work/vision/profiles' ? [profile] : {}),
  );
  render(
    <VisionApproval
      taskId="t1"
      info={{
        file: 'report.pdf',
        locations: ['第 3 页'],
        reason: '需要识别图像',
        message: '可能按服务规则计费',
      }}
      onChanged={onChanged}
    />,
  );
  HTMLElement.prototype.scrollIntoView = vi.fn();
  await waitFor(() => expect(request).toHaveBeenCalledTimes(1));
  expect(screen.getByText(/report.pdf.*第 3 页/)).toBeTruthy();
  expect(request).toHaveBeenCalledTimes(1);
  const selector = screen.getByRole('combobox', { name: '本任务的替代视觉服务' });
  expect(selector.tagName).toBe('BUTTON');
  fireEvent.keyDown(selector, { key: 'ArrowDown' });
  fireEvent.click(await screen.findByRole('option', { name: 'vision.example / visual' }));
  expect(screen.getByText(/会将图像发送到本机之外/)).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: '同意本任务使用所选服务' }));
  await waitFor(() =>
    expect(request).toHaveBeenCalledWith('/work/tasks/t1/vision', {
      method: 'POST',
      body: JSON.stringify({ approved: true, profile_id: 'v1', signature: 'sig' }),
    }),
  );
  expect(onChanged).toHaveBeenCalledOnce();
});

it('permits declining without configuring any fallback service', async () => {
  vi.mocked(request).mockResolvedValue([]);
  render(
    <VisionApproval taskId="t2" info={{ file: 'scan.pdf', locations: ['第 1 页'] }} onChanged={vi.fn()} />,
  );
  await screen.findByText(/目前没有可用的替代视觉模型/);
  expect(screen.getByRole('button', { name: '同意本任务使用所选服务' })).toHaveProperty('disabled', true);
  fireEvent.click(screen.getByRole('button', { name: '拒绝并保留已读内容' }));
  await waitFor(() =>
    expect(request).toHaveBeenCalledWith('/work/tasks/t2/vision', {
      method: 'POST',
      body: JSON.stringify({ approved: false }),
    }),
  );
});
