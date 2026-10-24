import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import '@testing-library/jest-dom/vitest';
import { afterEach, expect, it, vi } from 'vitest';
import { request } from './api';
import { AnnotationProvider } from './Annotations';
import { RegionAnnotation } from './RegionAnnotation';

vi.mock('./api', () => ({ request: vi.fn() }));
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it('saves a selected region in image coordinates rather than viewport pixels', async () => {
  vi.stubGlobal('PointerEvent', MouseEvent);
  let saved: Record<string, unknown> | undefined;
  vi.mocked(request).mockImplementation(async (_path, options) => {
    if (options?.method === 'POST') {
      saved = JSON.parse(String(options.body));
      return { ...saved, id: 'region-1', status: 'draft' };
    }
    return [];
  });
  render(
    <AnnotationProvider conversationId="chat-1">
      <RegionAnnotation
        src="/image"
        alt="示例图片"
        anchor={{
          source: { kind: 'attachment', id: 'image-1', version: 'a'.repeat(64) },
          target_id: 'image',
          name: '图片.png',
          location: '整张图片',
        }}
      />
    </AnnotationProvider>,
  );
  const surface = screen.getByRole('img', { name: '示例图片' }).parentElement!;
  vi.spyOn(surface, 'getBoundingClientRect').mockReturnValue({
    left: 0,
    top: 0,
    width: 100,
    height: 100,
    right: 100,
    bottom: 100,
    x: 0,
    y: 0,
    toJSON: () => ({}),
  });
  fireEvent.click(screen.getByRole('button', { name: '框选区域' }));
  fireEvent.pointerDown(surface, { clientX: 10, clientY: 20, button: 0 });
  fireEvent.pointerMove(surface, { clientX: 50, clientY: 60 });
  fireEvent.pointerUp(surface, { clientX: 50, clientY: 60 });
  fireEvent.click(screen.getByRole('button', { name: '批注选区' }));
  fireEvent.change(await screen.findByRole('textbox', { name: '修改意见' }), {
    target: { value: '裁剪这块区域' },
  });
  fireEvent.click(screen.getByRole('button', { name: '保存批注草稿' }));
  await screen.findByText('裁剪这块区域');
  expect(saved?.rect).toEqual([0.1, 0.2, 0.4, 0.4]);
});
