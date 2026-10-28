import { act, renderHook, waitFor, cleanup } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { useConversation } from './useConversation';
import { request, streamChat, type Message } from './api';

vi.mock('./api', () => ({ request: vi.fn(), streamChat: vi.fn() }));
const user: Message = {
  id: 'u',
  conversation_id: 'c',
  role: 'user',
  status: 'complete',
  content: '你好',
  created_at: '2026-10-15',
};
const assistant: Message = { ...user, id: 'a', role: 'assistant', content: '回复' };
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(request).mockResolvedValue([]);
});
afterEach(cleanup);

it('feeds speech deltas before completion and cancels speech on a failed stream', async () => {
  const events: string[] = [];
  const speech = {
    start: () => events.push('start'),
    delta: (text: string) => events.push(text),
    cancel: () => events.push('cancel'),
  };
  vi.mocked(streamChat).mockImplementation(async (_id, _text, _signal, emit) => {
    emit('user', user as unknown as Record<string, unknown>);
    emit('delta', { text: '第一句。' });
    expect(events).toEqual(['start', '第一句。']);
    throw new Error('模拟网络失败');
  });
  const complete = vi.fn();
  const { result } = renderHook(() => useConversation(complete, speech));
  await act(async () => {
    await result.current.send('你好', ['attachment-1']);
  });
  expect(events).toEqual(['start', '第一句。', 'cancel']);
  expect(complete).not.toHaveBeenCalled();
  expect(vi.mocked(streamChat).mock.calls[0][4]).toEqual(['attachment-1']);
});

it('starting or failing a new chat never creates an empty server conversation', async () => {
  vi.mocked(streamChat).mockRejectedValue(new Error('未配置模型'));
  const { result } = renderHook(() => useConversation(vi.fn()));
  act(() => result.current.selectConversation(null));
  await act(async () => {
    expect(await result.current.send('你好')).toBe(false);
  });
  expect(result.current.active).toBeNull();
  expect(vi.mocked(request).mock.calls.some(([, options]) => options?.method === 'POST')).toBe(false);
  expect(result.current.error).toBe('未配置模型');
});

it('accepts server conversation IDs, rejects overlapping sends and stops without polling', async () => {
  let finish: () => void = () => {};
  vi.mocked(streamChat).mockImplementation(async (_id, _text, _signal, emit) => {
    emit('user', user as unknown as Record<string, unknown>);
    await new Promise<void>((resolve) => {
      finish = resolve;
    });
    emit('done', { ...assistant, status: 'interrupted' } as unknown as Record<string, unknown>);
  });
  const complete = vi.fn();
  const { result } = renderHook(() => useConversation(complete));
  let pending: Promise<boolean>;
  act(() => {
    pending = result.current.send('你好');
  });
  await waitFor(() => expect(result.current.active).toBe('c'));
  await act(async () => {
    expect(await result.current.send('重复')).toBe(false);
  });
  vi.mocked(request).mockImplementation(async (path) => {
    if (path.endsWith('/stop')) {
      finish();
      return { ok: true };
    }
    return path.endsWith('/messages') ? [user, { ...assistant, status: 'interrupted' }] : [];
  });
  await act(async () => {
    await result.current.stopReply();
    await pending;
  });
  expect(streamChat).toHaveBeenCalledOnce();
  expect(complete).not.toHaveBeenCalled();
  expect(vi.mocked(request).mock.calls.filter(([path]) => path.endsWith('/messages'))).toHaveLength(1);
  expect(result.current.busy).toBe(false);
});

it('removes the selected conversation only after a successful delete', async () => {
  const { result } = renderHook(() => useConversation(vi.fn()));
  act(() => result.current.selectConversation('c'));
  await waitFor(() => expect(result.current.historyLoading).toBe(false));
  vi.mocked(request).mockRejectedValueOnce(new Error('正在回复'));
  await act(async () => {
    await expect(result.current.deleteConversation('c')).rejects.toThrow();
  });
  expect(result.current.active).toBe('c');
  vi.mocked(request).mockResolvedValue([]);
  await act(async () => {
    await result.current.deleteConversation('c');
  });
  expect(result.current.active).toBeNull();
});

it('selecting the current conversation preserves its transcript', async () => {
  vi.mocked(request).mockResolvedValue([user, assistant]);
  const { result } = renderHook(() => useConversation(vi.fn()));
  act(() => result.current.selectConversation('c'));
  await waitFor(() => expect(result.current.messages).toHaveLength(2));
  act(() => result.current.selectConversation('c'));
  expect(result.current.messages).toHaveLength(2);
});

it('refreshes a delivered file reply without replaying speech or duplicating messages', async () => {
  vi.mocked(request).mockResolvedValue([user, assistant]);
  const complete = vi.fn();
  const { result } = renderHook(() => useConversation(complete));
  act(() => result.current.selectConversation('c'));
  await waitFor(() => expect(result.current.messages).toHaveLength(2));
  const reply = { ...assistant, id: 'file-result-t', content: '文件总结' };
  vi.mocked(request).mockResolvedValue([user, assistant, reply]);
  await act(async () => {
    await result.current.refreshMessages();
    await result.current.refreshMessages();
  });
  expect(result.current.messages.map((message) => message.id)).toEqual(['u', 'a', 'file-result-t']);
  expect(complete).not.toHaveBeenCalled();
});

it('keeps a newer transcript when an older refresh arrives late', async () => {
  vi.mocked(request).mockResolvedValue([user, assistant]);
  const { result } = renderHook(() => useConversation(vi.fn()));
  act(() => result.current.selectConversation('c'));
  await waitFor(() => expect(result.current.messages).toHaveLength(2));
  let finishOld: (records: Message[]) => void = () => {};
  const reply = { ...assistant, id: 'file-result-new', content: '新文件结果' };
  vi.mocked(request)
    .mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finishOld = resolve;
        }),
    )
    .mockResolvedValue([user, assistant, reply]);
  let old: Promise<unknown>;
  act(() => {
    old = result.current.refreshMessages();
  });
  await act(async () => {
    await result.current.refreshMessages();
  });
  await act(async () => {
    finishOld([user, assistant]);
    await old;
  });
  expect(result.current.messages.map((item) => item.id)).toEqual(['u', 'a', 'file-result-new']);
});
