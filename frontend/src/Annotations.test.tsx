import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom/vitest';
import { afterEach, expect, it, vi } from 'vitest';
import { request } from './api';
import { AnnotationProvider, AnnotationTarget, AnnotationTray, useAnnotations } from './Annotations';

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

it('saves on outside interaction and reopens the same numbered draft on hover without a modal overlay', async () => {
  vi.mocked(request).mockReset();
  vi.mocked(request).mockImplementation(async (_path, options) =>
    options?.method === 'POST'
      ? { ...JSON.parse(String(options.body)), id: 'pin-1', status: 'draft', updated_at: 'now' }
      : [],
  );
  render(
    <AnnotationProvider conversationId="chat">
      <button>页面按钮</button>
      <AnnotationTarget
        anchor={{ source: { kind: 'attachment', id: 'f', version: 'a'.repeat(64) }, target_id: 's:0:A1' }}
        prepare={async () => ({
          source: { kind: 'attachment', id: 'f', version: 'a'.repeat(64) },
          target_id: 's:0:A1',
        })}
        label="A1"
      >
        单元格
      </AnnotationTarget>
      <AnnotationTray />
    </AnnotationProvider>,
  );
  fireEvent.click(screen.getByRole('button', { name: '批注A1' }));
  const input = await screen.findByRole('textbox', { name: '修改意见' });
  expect(screen.queryByTestId('dialog-overlay')).toBeNull();
  expect(document.querySelector('[data-slot="dialog-overlay"]')).toBeNull();
  fireEvent.change(input, { target: { value: '只修改姓名' } });
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
  fireEvent.pointerDown(screen.getByText('页面按钮'), { pointerType: 'mouse' });
  fireEvent.click(screen.getByText('页面按钮'));
  const pin = await screen.findByRole('button', { name: '批注 1' });
  fireEvent.mouseEnter(pin);
  expect(await screen.findByRole('textbox', { name: '修改意见' })).toHaveValue('只修改姓名');
  expect(vi.mocked(request).mock.calls.filter(([, options]) => options?.method === 'POST')).toHaveLength(1);
});

it('retains input and target when autosave fails, and never creates a pin for an empty draft', async () => {
  vi.mocked(request).mockReset();
  vi.mocked(request).mockImplementation(async (_path, options) => {
    if (options?.method === 'POST') throw new Error('版本冲突，请重新定位');
    return [];
  });
  render(
    <AnnotationProvider conversationId="chat">
      <AnnotationTarget
        label="正文"
        prepare={async () => ({
          source: { kind: 'attachment', id: 'f', version: 'a'.repeat(64) },
          target_id: 'p:0',
        })}
      >
        正文
      </AnnotationTarget>
    </AnnotationProvider>,
  );
  fireEvent.click(screen.getByRole('button', { name: '批注正文' }));
  const input = await screen.findByRole('textbox', { name: '修改意见' });
  fireEvent.keyDown(input, { key: 'Escape' });
  await waitFor(() => expect(screen.queryByRole('textbox')).toBeNull());
  expect(vi.mocked(request).mock.calls.some(([, options]) => options?.method === 'POST')).toBe(false);
  fireEvent.click(screen.getByRole('button', { name: '批注正文' }));
  fireEvent.change(await screen.findByRole('textbox', { name: '修改意见' }), {
    target: { value: '不能丢失' },
  });
  fireEvent.click(screen.getByRole('button', { name: '保存批注草稿' }));
  await screen.findByRole('alert');
  expect(screen.getByRole('textbox')).toHaveValue('不能丢失');
  expect(screen.queryByRole('button', { name: '批注 1' })).toBeNull();
});

it('does not reopen an old target when its save finishes after switching chats', async () => {
  let finish: (value: unknown) => void = () => {};
  vi.mocked(request).mockReset();
  vi.mocked(request).mockImplementation(async (_path, options) =>
    options?.method === 'POST'
      ? new Promise((resolve) => {
          finish = resolve;
        })
      : [],
  );
  const children = (
    <>
      <AnnotationTarget
        label="正文"
        prepare={async () => ({
          source: { kind: 'attachment', id: 'f', version: 'a'.repeat(64) },
          target_id: 'p:0',
        })}
      >
        正文
      </AnnotationTarget>
      <AnnotationTray />
    </>
  );
  const view = render(<AnnotationProvider conversationId="old">{children}</AnnotationProvider>);
  fireEvent.click(screen.getByRole('button', { name: '批注正文' }));
  fireEvent.change(await screen.findByRole('textbox', { name: '修改意见' }), {
    target: { value: '旧聊天意见' },
  });
  fireEvent.click(screen.getByRole('button', { name: '保存批注草稿' }));
  view.rerender(<AnnotationProvider conversationId="new">{children}</AnnotationProvider>);
  await act(async () =>
    finish({
      id: 'old-pin',
      source: { kind: 'attachment', id: 'f', version: 'a'.repeat(64) },
      target_id: 'p:0',
      comment: '旧聊天意见',
      status: 'draft',
    }),
  );
  expect(screen.queryByRole('textbox')).toBeNull();
  expect(screen.queryByText('旧聊天意见')).toBeNull();
  expect(screen.queryByRole('button', { name: '批注 1' })).toBeNull();
});

it('includes an open editor draft in unified submission only after it is saved', async () => {
  vi.mocked(request).mockReset();
  vi.mocked(request).mockImplementation(async (_path, options) =>
    options?.method === 'POST'
      ? { ...JSON.parse(String(options.body)), id: 'saved-before-send', status: 'draft' }
      : [],
  );
  const submitted = vi.fn();
  function Submit() {
    const annotations = useAnnotations();
    return <button onClick={async () => submitted(await annotations?.submission())}>统一发送</button>;
  }
  render(
    <AnnotationProvider conversationId="chat">
      <AnnotationTarget
        label="正文"
        prepare={async () => ({
          source: { kind: 'attachment', id: 'f', version: 'a'.repeat(64) },
          target_id: 'p:0',
        })}
      >
        正文
      </AnnotationTarget>
      <Submit />
    </AnnotationProvider>,
  );
  fireEvent.click(screen.getByRole('button', { name: '批注正文' }));
  fireEvent.change(await screen.findByRole('textbox', { name: '修改意见' }), {
    target: { value: '保存后提交' },
  });
  fireEvent.click(screen.getByRole('button', { name: '统一发送' }));
  await waitFor(() =>
    expect(submitted).toHaveBeenCalledWith(expect.objectContaining({ ids: ['saved-before-send'] })),
  );
  const body = String(
    vi.mocked(request).mock.calls.find(([, options]) => options?.method === 'POST')?.[1]?.body,
  );
  expect(body).not.toMatch(/token|BoundingClientRect|viewAnchor/);
});
