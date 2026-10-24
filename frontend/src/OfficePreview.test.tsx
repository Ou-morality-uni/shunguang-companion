import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import '@testing-library/jest-dom/vitest';
import { afterEach, expect, it, vi } from 'vitest';
import { request } from './api';
import { AnnotationProvider } from './Annotations';
import { ResourcePreview } from './ResourcePreview';

vi.mock('./api', () => ({ request: vi.fn() }));
afterEach(cleanup);

it('allows loading workbook cells beyond the first preview batch', async () => {
  vi.mocked(request).mockImplementation(async (path) => {
    if (String(path).includes('/annotations')) return [];
    if (String(path).includes('/capabilities')) return { office: { ready: false } };
    return {
      version: 'a'.repeat(64),
      name: 'Data.xlsx',
      targets: Array.from({ length: 51 }, (_, index) => ({
        id: `s:0:A${index + 1}`,
        kind: 'cell',
        text: `Value-${index + 1}`,
        location: `Data · A${index + 1}`,
      })),
    };
  });
  render(
    <AnnotationProvider conversationId="chat-1">
      <ResourcePreview resource={{ kind: 'artifact', id: 'task-1', title: 'Data.xlsx' }} />
    </AnnotationProvider>,
  );
  await screen.findByText('Value-1');
  expect(screen.queryByText('Value-51')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: '显示更多对象' }));
  expect(await screen.findByText('Value-51')).toBeInTheDocument();
});

it('previews a workbook as a coordinate-labelled table with per-cell annotations', async () => {
  vi.mocked(request).mockImplementation(async (path) => {
    if (String(path).includes('/annotations')) return [];
    if (String(path).includes('/capabilities')) return { office: { ready: false } };
    return {
      version: 'a'.repeat(64),
      name: 'Data.xlsx',
      targets: [
        { id: 's:0:A1', kind: 'cell', text: 'Item', location: 'Data · A1' },
        { id: 's:0:B1', kind: 'cell', text: 'Count', location: 'Data · B1' },
        { id: 's:0:A2', kind: 'cell', text: 'A', location: 'Data · A2' },
        { id: 's:0:B2', kind: 'cell', text: '12', location: 'Data · B2' },
      ],
    };
  });
  render(
    <AnnotationProvider conversationId="chat-1">
      <ResourcePreview resource={{ kind: 'artifact', id: 'task-1', title: 'Data.xlsx' }} />
    </AnnotationProvider>,
  );
  await screen.findByRole('table', { name: 'Data 单元格内容预览' });
  expect(screen.getByRole('columnheader', { name: 'B' })).toBeInTheDocument();
  expect(screen.getByRole('cell', { name: /12/ })).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: '批注Data · B2' }));
  await screen.findByRole('dialog', { name: '添加批注' });
});

it('opens a Word object as readable content and lets the user comment on that object', async () => {
  vi.mocked(request).mockImplementation(async (path) => {
    if (String(path).includes('/annotations')) return [];
    if (String(path).includes('/capabilities')) return { office: { ready: false } };
    return {
      version: 'a'.repeat(64),
      name: '报告.docx',
      targets: [{ id: 'p:0', kind: 'paragraph', text: '定位到这段正文', location: '正文第 1 段' }],
    };
  });
  render(
    <AnnotationProvider conversationId="chat-1">
      <ResourcePreview resource={{ kind: 'artifact', id: 'task-1', title: '报告.docx' }} />
    </AnnotationProvider>,
  );
  expect(await screen.findByText('定位到这段正文')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: '批注正文第 1 段' }));
  expect(await screen.findByRole('textbox', { name: '修改意见' })).toBeInTheDocument();
});
