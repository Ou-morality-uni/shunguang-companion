import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom/vitest';
import { afterEach, expect, it, vi } from 'vitest';
import { request } from './api';
import { AnnotationProvider, AnnotationTarget, AnnotationTray } from './Annotations';

vi.mock('./api', () => ({ request: vi.fn() }));
afterEach(cleanup);

it('keeps a newly saved draft when the initial draft-list request arrives late', async () => {
  let resolveList: (value: unknown) => void = () => {};
  const delayed = new Promise((resolve) => {
    resolveList = resolve;
  });
  vi.mocked(request).mockImplementation(async (_path, options) => {
    if (options?.method === 'POST')
      return { ...JSON.parse(String(options.body)), id: 'new-comment', status: 'draft', updated_at: 'stamp' };
    return delayed;
  });
  render(
    <AnnotationProvider conversationId="chat-1">
      <AnnotationTarget
        prepare={async () => ({
          source: { kind: 'attachment', id: 'file-1', version: 'a'.repeat(64) },
          target_id: 'p:0',
          name: '报告.docx',
          location: '正文',
        })}
        label="正文"
      >
        正文
      </AnnotationTarget>
      <AnnotationTray />
    </AnnotationProvider>,
  );
  fireEvent.click(screen.getByRole('button', { name: '批注正文' }));
  fireEvent.change(await screen.findByRole('textbox', { name: '修改意见' }), {
    target: { value: '保留这条意见' },
  });
  fireEvent.click(screen.getByRole('button', { name: '保存批注草稿' }));
  await screen.findByText('保留这条意见');
  await act(async () => {
    resolveList([]);
  });
  expect(screen.getByText('保留这条意见')).toBeInTheDocument();
});

it('adds a draft from a preview target and restores the saved comment', async () => {
  const drafts: Record<string, unknown>[] = [];
  vi.mocked(request).mockImplementation(async (_path, options) => {
    if (options?.method === 'POST') {
      const value = {
        ...JSON.parse(String(options.body)),
        id: 'annotation-1',
        status: 'draft',
        updated_at: 'stamp',
      };
      drafts.push(value);
      return value;
    }
    return drafts.slice();
  });
  const prepare = async () => ({
    source: { kind: 'attachment' as const, id: 'file-1', version: 'a'.repeat(64) },
    target_id: 'p:0',
    name: '报告.docx',
    location: '正文第 1 段',
  });
  const mount = () =>
    render(
      <AnnotationProvider conversationId="chat-1">
        <AnnotationTarget prepare={prepare} label="正文第 1 段">
          需要修改的正文
        </AnnotationTarget>
        <AnnotationTray />
      </AnnotationProvider>,
    );
  const view = mount();
  fireEvent.click(screen.getByRole('button', { name: '批注正文第 1 段' }));
  fireEvent.change(await screen.findByRole('textbox', { name: '修改意见' }), {
    target: { value: '请精简这段' },
  });
  fireEvent.click(screen.getByRole('button', { name: '保存批注草稿' }));
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  expect(screen.getByText('请精简这段')).toBeInTheDocument();
  expect(drafts[0].target_id).toBe('p:0');
  view.unmount();
  mount();
  expect(await screen.findByText('请精简这段')).toBeInTheDocument();
});
