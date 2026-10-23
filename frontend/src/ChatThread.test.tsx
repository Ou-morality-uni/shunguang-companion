import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { request } from './api';
import { ChatThread } from './ChatThread';

vi.mock('./api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./api')>()),
  request: vi.fn(),
}));
vi.mock('./FileTasks', () => ({ AttachmentCard: () => null, ChatFileTasks: () => null }));
vi.mock('./useAudioQueue', () => ({ useCompanionAudio: () => ({ busy: false, error: null }) }));
afterEach(() => {
  cleanup();
  vi.resetAllMocks();
  vi.unstubAllGlobals();
});

it('stages an uploaded file without starting a task, then sends its reference with the user instruction', async () => {
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  );
  vi.mocked(request).mockResolvedValue({ workspace: { id: 'w1' }, path: 'copy.txt', task: { id: 'u1' } });
  const onSend = vi.fn().mockResolvedValue(true);
  render(
    <ChatThread
      messages={[]}
      partial={null}
      busy={false}
      loading={false}
      configured
      conversationId={null}
      onSend={onSend}
      onStop={vi.fn()}
      onSettings={vi.fn()}
      onVoice={vi.fn()}
      onTools={vi.fn()}
      onWork={vi.fn()}
    />,
  );
  const file = new File(['source content'], 'source.txt', { type: 'text/plain' });
  fireEvent.change(screen.getByLabelText('上传聊天附件'), { target: { files: [file] } });
  await screen.findByRole('button', { name: '移除附件 source.txt' });
  expect(onSend).not.toHaveBeenCalled();
  expect(request).toHaveBeenCalledOnce();
  fireEvent.change(screen.getByLabelText('给瞬光伴行发送消息'), { target: { value: '总结整份资料' } });
  fireEvent.click(screen.getByRole('button', { name: '发送消息' }));
  await waitFor(() => expect(onSend).toHaveBeenCalledWith('总结整份资料', ['u1']));
});
