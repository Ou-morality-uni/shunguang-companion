import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom/vitest';
import { afterEach, expect, it, vi } from 'vitest';
import { AnnotationProvider } from './Annotations';
import { ContinuousPreview } from './ContinuousPreview';
import { recognizePage } from './localOcr';
import { request } from './api';

vi.mock('./api', () => ({ request: vi.fn() }));
vi.mock('./localOcr', () => ({ recognizePage: vi.fn() }));
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.resetAllMocks();
});

it('recognizes an image only on request and saves a positioned OCR comment as a draft', async () => {
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
    return this.matches('.ocr-text-layer span') ? new DOMRect(20, 30, 80, 20) : new DOMRect(0, 0, 200, 100);
  });
  vi.mocked(request).mockImplementation(async (_path, options) =>
    options?.method === 'POST' ? { id: 'draft', ...JSON.parse(String(options.body)), status: 'draft' } : [],
  );
  vi.mocked(recognizePage).mockResolvedValue([
    { text: '合同金额', confidence: 95, rect: [0.1, 0.3, 0.4, 0.2] },
  ]);
  render(
    <AnnotationProvider conversationId="chat">
      <ContinuousPreview
        image
        url="/image"
        imageUrl={() => '/image'}
        anchor={{
          source: { kind: 'attachment', id: 'image', version: 'a'.repeat(64) },
          target_id: 'image',
          name: 'image.png',
        }}
      />
    </AnnotationProvider>,
  );
  expect(recognizePage).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: '识别文字' }));
  const word = await screen.findByText('合同金额');
  fireEvent.contextMenu(word);
  fireEvent.click(await screen.findByRole('menuitem', { name: '添加批注' }));
  expect(await screen.findByRole('dialog', { name: '添加批注' })).toHaveTextContent('合同金额');
  fireEvent.change(screen.getByRole('textbox', { name: '修改意见' }), {
    target: { value: '请核对这个金额' },
  });
  fireEvent.click(screen.getByRole('button', { name: '保存批注草稿' }));
  await waitFor(() =>
    expect(request).toHaveBeenCalledWith('/work/annotations', expect.objectContaining({ method: 'POST' })),
  );
  const payload = JSON.parse(
    String(vi.mocked(request).mock.calls.find(([, options]) => options?.method === 'POST')![1]!.body),
  );
  expect(payload).toMatchObject({
    quote: '合同金额',
    text_origin: 'ocr',
    regions: [{ page: 1, rect: [0.1, 0.3, 0.4, 0.2] }],
  });
});
