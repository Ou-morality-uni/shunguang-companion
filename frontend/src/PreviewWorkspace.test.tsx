import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { PreviewWorkspace } from './PreviewWorkspace';
import { AttachmentCard, ArtifactCard } from './FileTasks';
import { AudioContextValue, type AudioController } from './useAudioQueue';
import { HistorySources } from './Evidence';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  sessionStorage.clear();
});

it('opens a recalled conversation source in a tab only after clicking and reloads its original text', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockImplementation(() =>
      Promise.resolve(
        new Response(
          JSON.stringify({
            message_id: 'history-one',
            conversation_id: 'old',
            title: '预算核对',
            role: 'user',
            time: '2026-10-23T12:00:00Z',
            text: '这是来源原文 FULL_SOURCE_MARKER。',
          }),
          { headers: { 'content-type': 'application/json' } },
        ),
      ),
    ),
  );
  render(
    <PreviewWorkspace resetKey="history-chat">
      <HistorySources
        sources={[
          {
            message_id: 'history-one',
            conversation_id: 'old',
            title: '预算核对',
            role: 'user',
            time: '2026-10-23T12:00:00Z',
            text: '交通费是320元。',
          },
        ]}
      />
    </PreviewWorkspace>,
  );
  expect(screen.queryByRole('tab')).toBeNull();
  fireEvent.click(screen.getByText(/回忆来源/));
  fireEvent.click(screen.getByRole('button', { name: '查看旧对话来源：预算核对' }));
  expect(await screen.findByRole('tab', { name: '旧对话 · 预算核对' })).toBeTruthy();
  expect(await screen.findByText('这是来源原文 FULL_SOURCE_MARKER。')).toBeTruthy();
  expect(vi.mocked(fetch).mock.calls[0][0]).toBe('/api/memories/history/history-one');
  expect(JSON.stringify(sessionStorage)).not.toContain('FULL_SOURCE_MARKER');
});

it('only reads the full artifact after the user explicitly requests playback', async () => {
  const enqueue = vi.fn();
  const text = '# 详细总结\n\n完整内容保存在这里。';
  vi.stubGlobal(
    'fetch',
    vi.fn().mockImplementation(() => Promise.resolve(new Response(text))),
  );
  render(
    <AudioContextValue.Provider value={{ enqueueDocument: enqueue } as unknown as AudioController}>
      <PreviewWorkspace>
        <ArtifactCard
          task={{
            id: 'read-full',
            workspace_id: 'out',
            title: '资料总结',
            status: 'complete',
            steps: [],
            origin: 'chat',
            conversation_id: 'c',
            error: '',
            can_restore: false,
            can_retry_summary: false,
            created_at: '',
            updated_at: '',
            context: { artifact: { name: '资料总结.md', path: 'task/资料总结.md', workspace_id: 'out' } },
          }}
        />
      </PreviewWorkspace>
    </AudioContextValue.Provider>,
  );
  fireEvent.click(screen.getByRole('button', { name: '预览总结文件' }));
  await screen.findByText('完整内容保存在这里。');
  expect(enqueue).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: '朗读完整总结' }));
  expect(enqueue).toHaveBeenCalledWith(text, '资料总结.md');
});

it('restores resource tabs after a page reload without storing file contents', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockImplementation(() =>
      Promise.resolve(
        new Response(
          JSON.stringify({
            blocks: [{ location: '第 1 行', text: 'PRIVATE_DOCUMENT_CONTENT' }],
            warnings: [],
          }),
          { headers: { 'content-type': 'application/json' } },
        ),
      ),
    ),
  );
  const view = render(
    <PreviewWorkspace resetKey="reload-chat">
      <AttachmentCard
        attachment={{ id: 'reload-one', name: '资料.txt', workspace_id: 'w', path: 'one.txt', bytes: 1 }}
      />
    </PreviewWorkspace>,
  );
  fireEvent.click(screen.getByRole('button', { name: '预览 资料.txt' }));
  await screen.findByText('PRIVATE_DOCUMENT_CONTENT');
  view.unmount();
  render(
    <PreviewWorkspace resetKey="reload-chat">
      <p>继续聊天</p>
    </PreviewWorkspace>,
  );
  expect(await screen.findByRole('tab', { name: '资料.txt' })).toBeTruthy();
  await screen.findByText('PRIVATE_DOCUMENT_CONTENT');
  expect(JSON.stringify(sessionStorage)).not.toContain('PRIVATE_DOCUMENT_CONTENT');
});

it('keeps two file tabs and restores each conversation workspace when switching back', async () => {
  vi.stubGlobal(
    'fetch',
    vi
      .fn()
      .mockImplementation(() =>
        Promise.resolve(
          new Response(
            JSON.stringify({ blocks: [{ location: '第 1 行', text: '可核对内容' }], warnings: [] }),
            { headers: { 'content-type': 'application/json' } },
          ),
        ),
      ),
  );
  function Chat({ id }: { id: string }) {
    return (
      <PreviewWorkspace resetKey={id}>
        <AttachmentCard
          key={`${id}-one`}
          attachment={{ id: `${id}-one`, name: '第一份.txt', workspace_id: 'w', path: 'one.txt', bytes: 1 }}
        />
        <AttachmentCard
          key={`${id}-two`}
          attachment={{ id: `${id}-two`, name: '第二份.txt', workspace_id: 'w', path: 'two.txt', bytes: 1 }}
        />
      </PreviewWorkspace>
    );
  }
  const view = render(<Chat id="chat-a" />);
  expect(screen.queryByRole('region', { name: '文件预览' })).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: '预览 第一份.txt' }));
  await screen.findByText('可核对内容');
  fireEvent.click(screen.getByRole('button', { name: '预览 第二份.txt' }));
  expect(await screen.findByRole('tab', { name: '第一份.txt' })).toBeTruthy();
  expect(screen.getByRole('tab', { name: '第二份.txt' }).getAttribute('aria-selected')).toBe('true');
  view.rerender(<Chat id="chat-b" />);
  expect(screen.queryByRole('region', { name: '文件预览' })).toBeNull();
  view.rerender(<Chat id="chat-a" />);
  expect(await screen.findByRole('tab', { name: '第二份.txt' })).toBeTruthy();
  fireEvent.click(screen.getByRole('tab', { name: '第一份.txt' }));
  expect(screen.getByRole('tab', { name: '第一份.txt' }).getAttribute('aria-selected')).toBe('true');
});

it('returns to the original artifact button even if focus moves while its file loads', async () => {
  let resolve!: (value: Response) => void;
  vi.stubGlobal(
    'fetch',
    vi.fn(
      () =>
        new Promise<Response>((done) => {
          resolve = done;
        }),
    ),
  );
  render(
    <PreviewWorkspace>
      <button>继续工作</button>
      <ArtifactCard
        task={{
          id: 'saved',
          workspace_id: 'out',
          title: '总结',
          status: 'complete',
          steps: [],
          origin: 'chat',
          conversation_id: 'c1',
          error: '',
          can_restore: false,
          can_retry_summary: false,
          created_at: '',
          updated_at: '',
          context: { artifact: { name: '资料总结.md', path: 'task/资料总结.md', workspace_id: 'out' } },
        }}
      />
    </PreviewWorkspace>,
  );
  const trigger = screen.getByRole('button', { name: '预览总结文件' });
  trigger.focus();
  fireEvent.click(trigger);
  screen.getByRole('button', { name: '继续工作' }).focus();
  resolve(new Response('# 保存的文件'));
  const panel = await screen.findByRole('region', { name: '文件预览' });
  await within(panel).findByRole('heading', { name: '保存的文件' });
  fireEvent.keyDown(panel, { key: 'Escape' });
  expect(document.activeElement).toBe(trigger);
});

it('opens an attachment beside chat, supports keyboard resizing and restores focus when closed', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          blocks: [{ location: '正文第 8 块', text: '可核对的原文' }],
          warnings: [],
        }),
        { headers: { 'content-type': 'application/json' } },
      ),
    ),
  );
  render(
    <PreviewWorkspace>
      <div role="region" aria-label="聊天内容" className="conversation-scroll">
        继续聊天
      </div>
      <AttachmentCard
        attachment={{
          id: 'u1',
          name: '报告.txt',
          workspace_id: 'w1',
          path: 'copy.docx',
          bytes: 1024,
        }}
      />
    </PreviewWorkspace>,
  );
  const trigger = screen.getByRole('button', { name: '预览 报告.txt' });
  trigger.focus();
  fireEvent.click(trigger);
  const panel = await screen.findByRole('region', { name: '文件预览' });
  expect(await within(panel).findByText('可核对的原文')).toBeTruthy();
  const divider = screen.getByRole('separator', { name: '调整预览宽度' });
  expect(divider.getAttribute('aria-valuenow')).toBe('46');
  fireEvent.keyDown(divider, { key: 'ArrowLeft' });
  expect(divider.getAttribute('aria-valuenow')).toBe('51');
  fireEvent.click(within(panel).getByRole('button', { name: '放大预览' }));
  expect(within(panel).getByRole('button', { name: '还原并排' })).toBeTruthy();
  expect(screen.getByText('继续聊天').closest('.preview-main')?.hasAttribute('inert')).toBe(false);
  vi.stubGlobal('PointerEvent', MouseEvent);
  vi.spyOn(divider.parentElement!, 'getBoundingClientRect').mockReturnValue({
    right: 1000,
    width: 1000,
  } as DOMRect);
  divider.setPointerCapture = vi.fn();
  divider.hasPointerCapture = () => true;
  const chatScroll = screen.getByRole('region', { name: '聊天内容' });
  chatScroll.scrollTop = 120;
  fireEvent.pointerDown(divider);
  fireEvent.pointerMove(divider, { clientX: 100 });
  fireEvent.pointerMove(divider, { clientX: 0 });
  chatScroll.scrollTop = 0;
  fireEvent.click(screen.getByRole('button', { name: '展开聊天' }));
  expect(divider.getAttribute('aria-valuenow')).toBe('60');
  expect(chatScroll.scrollTop).toBe(120);
  fireEvent.keyDown(divider, { key: 'End' });
  expect(divider.getAttribute('aria-valuenow')).toBe('100');
  fireEvent.click(screen.getByRole('button', { name: '展开聊天' }));
  expect(screen.getByText('继续聊天').closest('.preview-main')?.hasAttribute('inert')).toBe(false);
  fireEvent.keyDown(divider, { key: 'Home' });
  expect(divider.getAttribute('aria-valuenow')).toBe('0');
  fireEvent.click(screen.getByRole('button', { name: '展开预览' }));
  expect(divider.getAttribute('aria-valuenow')).not.toBe('0');
  fireEvent.click(within(panel).getByRole('button', { name: '关闭预览' }));
  expect(screen.queryByRole('region', { name: '文件预览' })).toBeNull();
  expect(document.activeElement).toBe(trigger);
  expect(screen.getByText('继续聊天')).toBeTruthy();
});

it('keeps keyboard focus inside a narrow-window preview and returns to chat on Escape', async () => {
  vi.stubGlobal('matchMedia', () => ({ matches: true, addEventListener() {}, removeEventListener() {} }));
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ blocks: [], warnings: [] }), {
        headers: { 'content-type': 'application/json' },
      }),
    ),
  );
  render(
    <PreviewWorkspace>
      <AttachmentCard
        attachment={{ id: 'u2', name: '窄屏.txt', workspace_id: 'w1', path: 'n.txt', bytes: 1 }}
      />
    </PreviewWorkspace>,
  );
  const trigger = screen.getByRole('button', { name: '预览 窄屏.txt' });
  trigger.focus();
  fireEvent.click(trigger);
  const panel = await screen.findByRole('region', { name: '文件预览' });
  const buttons = Array.from(panel.querySelectorAll<HTMLButtonElement>('button'));
  buttons.at(-1)!.focus();
  fireEvent.keyDown(panel, { key: 'Tab' });
  expect(document.activeElement).toBe(within(panel).getByRole('button', { name: '放大预览' }));
  fireEvent.keyDown(panel, { key: 'Escape' });
  expect(screen.queryByRole('region', { name: '文件预览' })).toBeNull();
  expect(document.activeElement).toBe(trigger);
});

it('drops obsolete saved task panels while retaining file preview tabs', async () => {
  sessionStorage.setItem(
    'shunguang.resource-tabs.v1',
    JSON.stringify({
      chat: {
        tabs: [
          { kind: 'artifact', id: 'result', title: 'result.xlsx' },
          { kind: 'task', id: 'old', title: '内部任务面板' },
        ],
        active: 'task:old',
        visible: true,
      },
    }),
  );
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ blocks: [] }))));
  render(
    <PreviewWorkspace resetKey="chat">
      <p>聊天正文</p>
    </PreviewWorkspace>,
  );
  expect(screen.queryByText('内部任务面板')).toBeNull();
  expect(await screen.findByRole('heading', { name: 'result.xlsx' })).toBeTruthy();
});
