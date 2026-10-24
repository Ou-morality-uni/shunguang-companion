import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom/vitest';
import { afterEach, expect, it, vi } from 'vitest';
import { request } from './api';
import { OfficeCapabilities } from './OfficeCapabilities';

vi.mock('./api', () => ({ request: vi.fn() }));
afterEach(cleanup);

it('shows unavailable Office features and rechecks after the engine is installed', async () => {
  vi.mocked(request)
    .mockResolvedValueOnce({
      office: {
        ready: false,
        message: 'Office 页面预览、PDF 导出与 Excel 重算暂不可用。',
        install_url: 'https://www.libreoffice.org/download/download-libreoffice/',
      },
      formats: {},
    })
    .mockResolvedValueOnce({
      office: { ready: true, version: 'LibreOffice test', message: 'Office 引擎已就绪。' },
      formats: {},
    });
  render(<OfficeCapabilities />);
  expect(await screen.findByText(/Office 页面预览、PDF 导出与 Excel 重算暂不可用/)).toBeInTheDocument();
  expect(screen.getByRole('link', { name: '官方安装说明' })).toHaveAttribute(
    'href',
    'https://www.libreoffice.org/download/download-libreoffice/',
  );
  fireEvent.click(screen.getByRole('button', { name: '重新检测' }));
  await waitFor(() => expect(screen.getByText('Office 引擎已就绪。')).toBeInTheDocument());
  expect(screen.queryByRole('link', { name: '官方安装说明' })).not.toBeInTheDocument();
});
