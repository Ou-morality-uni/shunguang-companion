import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { request } from './api';
import { ChatThread } from './ChatThread';
const originalScrollTo = HTMLElement.prototype.scrollTo;

vi.mock('./api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./api')>()),
  request: vi.fn(),
}));
vi.mock('./FileTasks', () => ({ AttachmentCard: () => null, ChatFileTasks: () => null }));
vi.mock('./useAudioQueue', () => ({
  useCompanionAudio: () => ({ busy: false, error: null, setInputActive: vi.fn() }),
}));
afterEach(() => {
  cleanup();
  vi.resetAllMocks();
  vi.unstubAllGlobals();
  HTMLElement.prototype.scrollTo = originalScrollTo;
});

it('chooses a saved service model for a new conversation without sending or losing the draft', async () => {
  HTMLElement.prototype.scrollTo = vi.fn();
  HTMLElement.prototype.scrollIntoView = vi.fn();
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  );
  vi.mocked(request).mockImplementation(async (path) => {
    if (path === '/model-options')
      return [
        { id: 'one', label: '服务一', configured: true, models: [{ id: 'first', efforts: ['default'] }] },
        {
          id: 'two',
          label: '服务二',
          configured: true,
          models: [{ id: 'second', efforts: ['default', 'low', 'high'] }],
        },
      ];
    if (path === '/model-default')
      return { profile_id: 'one', model: 'first', effort: 'default', efforts: ['default'], configured: true };
    throw new Error('Unexpected request ' + path);
  });
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
  const input = screen.getByLabelText('给瞬光伴行发送消息') as HTMLTextAreaElement;
  fireEvent.change(input, { target: { value: '请帮我核对资料' } });
  const models = await screen.findByRole('combobox', { name: '当前会话模型' });
  await waitFor(() => expect(models.textContent).toContain('first'));
  fireEvent.keyDown(models, { key: 'ArrowDown' });
  fireEvent.click(await screen.findByRole('option', { name: 'second' }));
  fireEvent.keyDown(screen.getByRole('combobox', { name: '思考强度' }), { key: 'ArrowDown' });
  fireEvent.click(await screen.findByRole('option', { name: '低' }));
  expect(input.value).toBe('请帮我核对资料');
  expect(onSend).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: '发送消息' }));
  await waitFor(() =>
    expect(onSend).toHaveBeenCalledWith('请帮我核对资料', [], {
      profile_id: 'two',
      model: 'second',
      effort: 'low',
    }),
  );
  expect(vi.mocked(request).mock.calls.every(([, options]) => !options?.method)).toBe(true);
});

it('records on two clicks, releases the microphone and appends editable transcription without sending', async () => {
  HTMLElement.prototype.scrollTo = vi.fn();
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  );
  const stopTrack = vi.fn();
  vi.stubGlobal('navigator', {
    mediaDevices: { getUserMedia: vi.fn().mockResolvedValue({ getTracks: () => [{ stop: stopTrack }] }) },
  });
  vi.stubGlobal(
    'MediaRecorder',
    class {
      static isTypeSupported = () => true;
      state = 'inactive';
      mimeType = 'audio/webm';
      ondataavailable: ((event: { data: Blob }) => void) | null = null;
      onstop: (() => void) | null = null;
      start() {
        this.state = 'recording';
      }
      stop() {
        this.state = 'inactive';
        this.ondataavailable?.({ data: new Blob(['audio'], { type: this.mimeType }) });
        this.onstop?.();
      }
    },
  );
  vi.mocked(request).mockImplementation(async (path) =>
    path === '/asr/transcribe' ? { text: '帮我总结资料。' } : path === '/model-options' ? [] : null,
  );
  const onSend = vi.fn().mockResolvedValue(true);
  render(
    <ChatThread
      messages={[]}
      partial={null}
      busy={false}
      loading={false}
      configured
      conversationId={null}
      asrSettings={{
        enabled: true,
        configured: true,
        base_url: 'https://example.com/v1',
        model: 'test',
        profile_id: '',
        timeout: 60,
        has_api_key: true,
      }}
      onSend={onSend}
      onStop={vi.fn()}
      onSettings={vi.fn()}
      onVoice={vi.fn()}
      onTools={vi.fn()}
      onWork={vi.fn()}
    />,
  );
  const input = screen.getByLabelText('给瞬光伴行发送消息') as HTMLTextAreaElement;
  fireEvent.change(input, { target: { value: '先看看。' } });
  fireEvent.click(screen.getByRole('button', { name: '开始语音输入' }));
  const finish = await screen.findByRole('button', { name: '结束录音并转写' });
  fireEvent.change(input, { target: { value: '先看看，我补充一点。' } });
  fireEvent.click(finish);
  await waitFor(() => expect(input.value).toBe('先看看，我补充一点。\n帮我总结资料。'));
  expect(stopTrack).toHaveBeenCalledOnce();
  expect(onSend).not.toHaveBeenCalled();
  const call = vi.mocked(request).mock.calls.find(([path]) => path === '/asr/transcribe')!;
  expect(call[1]?.headers).toEqual({ 'Content-Type': 'audio/webm' });
  fireEvent.change(input, { target: { value: '改好的草稿' } });
  fireEvent.click(screen.getByRole('button', { name: '发送消息' }));
  await waitFor(() => expect(onSend).toHaveBeenCalledWith('改好的草稿', [], undefined));
});

it('fills a file-task suggestion for editing without sending until the user confirms', async () => {
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  );
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
  fireEvent.click(screen.getByRole('button', { name: /总结资料/ }));
  const input = screen.getByLabelText('给瞬光伴行发送消息') as HTMLTextAreaElement;
  expect(input.value).toBe('帮我总结这份资料，梳理重点，并注明对应位置。');
  expect(document.activeElement).toBe(input);
  expect(onSend).not.toHaveBeenCalled();
  fireEvent.change(input, { target: { value: '只总结第二章，稍后附上文件。' } });
  fireEvent.click(screen.getByRole('button', { name: '发送消息' }));
  await waitFor(() => expect(onSend).toHaveBeenCalledWith('只总结第二章，稍后附上文件。', [], undefined));
});

it('renders reply tables as accessible tables while keeping fenced code readable', async () => {
  HTMLElement.prototype.scrollTo = vi.fn();
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  );
  render(
    <ChatThread
      messages={[
        {
          id: 'table',
          role: 'assistant',
          status: 'complete',
          created_at: '2026-10-23T12:00:00Z',
          content: '| 文件 | 结果 |\n| --- | --- |\n| 报告.pdf | 已读取 |\n\n```python\nprint("ready")\n```',
        },
      ]}
      partial={null}
      busy={false}
      loading={false}
      configured
      conversationId="c1"
      onSend={vi.fn()}
      onStop={vi.fn()}
      onSettings={vi.fn()}
      onVoice={vi.fn()}
      onTools={vi.fn()}
      onWork={vi.fn()}
    />,
  );
  expect(await screen.findByRole('table')).toBeTruthy();
  expect(screen.getByRole('cell', { name: '报告.pdf' })).toBeTruthy();
  expect(screen.getByText('print("ready")')).toBeTruthy();
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
  vi.mocked(request).mockImplementation(async (path) =>
    path.startsWith('/work/upload')
      ? { workspace: { id: 'w1' }, path: 'copy.txt', task: { id: 'u1' } }
      : path === '/model-options'
        ? []
        : null,
  );
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
  expect(vi.mocked(request).mock.calls.filter(([path]) => path.startsWith('/work/upload'))).toHaveLength(1);
  fireEvent.change(screen.getByLabelText('给瞬光伴行发送消息'), { target: { value: '总结整份资料' } });
  fireEvent.click(screen.getByRole('button', { name: '发送消息' }));
  await waitFor(() => expect(onSend).toHaveBeenCalledWith('总结整份资料', ['u1'], undefined));
});
