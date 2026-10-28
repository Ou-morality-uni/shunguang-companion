import { render, screen, cleanup } from '@testing-library/react';
import '@testing-library/jest-dom/vitest';
import { afterEach, it, expect, vi } from 'vitest';
import { request } from './api';
import { WorkSpace } from './WorkSpace';
vi.mock('./api', () => ({ request: vi.fn() }));
afterEach(cleanup);
it('shows compact uploaded files without manual tasks, output settings, or repeated upload controls', async () => {
  vi.mocked(request).mockImplementation(async (path) =>
    path === '/work/uploads' ? [{ id: 'file', name: '资料.pdf', bytes: 2400, created_at: '2026-10-25' }] : [],
  );
  render(<WorkSpace />);
  expect(await screen.findByText('资料.pdf')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: '预览 资料.pdf' })).toBeInTheDocument();
  expect(screen.queryByRole('region', { name: '安排文件任务' })).toBeNull();
  expect(screen.queryByText('成果保存位置')).toBeNull();
  expect(screen.queryByLabelText('选择上传文件')).toBeNull();
});

it('shows upload dates with local hours and minutes so same-day files can be distinguished', async () => {
  vi.mocked(request).mockResolvedValue([
    {
      id: 'file',
      name: '时间资料.pdf',
      bytes: 1200,
      created_at: new Date(2026, 9, 27, 14, 23).toISOString(),
    },
  ]);
  render(<WorkSpace />);
  const time = await screen.findByText(/14:23/);
  expect(time.textContent).toContain('2026');
  expect(time.textContent).toContain('10');
  expect(time.textContent).toContain('27');
});
