import { createContext, useContext, useEffect, useMemo, useRef, useState } from 'react';
import {
  AssistantRuntimeProvider,
  useExternalStoreRuntime,
  ThreadPrimitive,
  ComposerPrimitive,
  MessagePrimitive,
  ActionBarPrimitive,
  useAuiState,
  type ThreadMessageLike,
} from '@assistant-ui/react';
import { MarkdownTextPrimitive } from '@assistant-ui/react-markdown';
import { motion } from 'motion/react';
import {
  ArrowDown,
  ArrowUp,
  ArrowUpRight,
  BookOpen,
  Copy,
  MessageSquare,
  AudioLines,
  Play,
  Sparkles,
  Square,
  Wrench,
  Paperclip,
  X,
} from 'lucide-react';
import { avatarUrl, request, type Attachment, type Message, type Source, type ToolEvent } from './api';
import { AttachmentCard, ChatFileTasks } from './FileTasks';
import { Sources, ToolFeedback } from './Evidence';
import { useCompanionAudio } from './useAudioQueue';
import { ResourceImage } from './ResourceImage';
import { MessageSticker } from './MessageSticker';
import { MAX_MESSAGE_LENGTH } from './generated/limits';
const MarkdownText = () => <MarkdownTextPrimitive defer smooth />;
const MessagesContext = createContext<Message[]>([]);

const starters = [
  { icon: Sparkles, label: '初次相识', sub: '从一句你好开始', text: '你好，先介绍一下你自己吧。' },
  { icon: MessageSquare, label: '说说今天', sub: '分享你的日常碎片', text: '今天有点累，想和你聊一会儿。' },
  { icon: BookOpen, label: '世界漫游', sub: '聊聊新艾利都的故事', text: '你现在知道哪些关于绝区零的设定？' },
];

function ChatMessage() {
  const message = useAuiState((state) => state.message);
  const user = message.role === 'user';
  const record = useContext(MessagesContext).find((item) => item.id === message.id);
  const audio = useCompanionAudio();
  return (
    <MessagePrimitive.Root className={`message ${user ? 'user' : 'assistant'}`}>
      <motion.div
        className="message-layout"
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.25 }}
      >
        <div className="message-avatar">
          {user ? '你' : <ResourceImage src={avatarUrl} alt="叶瞬光默认头像" />}
        </div>
        <div className="message-body">
          <div className="message-meta">
            {user ? '你' : '叶瞬光'}
            <span>
              {message.createdAt.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}
            </span>
            {message.status?.type === 'running' && <span className="message-status">正在回复</span>}
            {message.status?.type === 'incomplete' && (
              <span className="message-status">
                {message.status.reason === 'cancelled' ? '已停止' : '未完成'}
              </span>
            )}
          </div>
          <div className="message-text">
            <MessagePrimitive.Parts components={{ Text: MarkdownText }} />
            {message.content.every((part) => part.type === 'text' && !part.text) && (
              <span className="thinking">
                正在组织语言<span>…</span>
              </span>
            )}
          </div>
          {!user && record?.status === 'complete' && record.sticker && (
            <MessageSticker key={record.sticker.id} sticker={record.sticker} />
          )}
          <ToolFeedback tools={record?.tools} />
          {record?.attachments?.map((attachment) => (
            <AttachmentCard key={attachment.id} attachment={attachment} />
          ))}
          <Sources sources={record?.sources} />
          <ActionBarPrimitive.Root className="message-actions">
            <ActionBarPrimitive.Copy className="copy-button" aria-label="复制消息">
              <Copy size={13} />
              <span className="copy-label">复制</span>
              <span className="copied-label">已复制</span>
            </ActionBarPrimitive.Copy>
            {!user && record?.content && message.status?.type !== 'running' && (
              <button
                className="copy-button"
                onClick={() => audio.enqueue(record.content)}
                aria-label="播放这条回复"
              >
                <Play size={13} />
                播放
              </button>
            )}
          </ActionBarPrimitive.Root>
        </div>
      </motion.div>
    </MessagePrimitive.Root>
  );
}

type Props = {
  messages: Message[];
  partial: string | null;
  busy: boolean;
  loading: boolean;
  configured: boolean;
  tools?: ToolEvent[];
  sources?: Source[];
  onSend: (text: string, attachments?: string[]) => Promise<boolean>;
  onStop: () => void;
  onSettings: () => void;
  onVoice: () => void;
  onTools: () => void;
  conversationId: string | null;
  onWork: () => void;
};

export function ChatThread({
  messages,
  partial,
  busy,
  loading,
  configured,
  tools,
  sources,
  onSend,
  onStop,
  onSettings,
  onVoice,
  onTools,
  conversationId,
  onWork,
}: Props) {
  const audio = useCompanionAudio();
  const [attachments, setAttachments] = useState<Attachment[]>([]),
    [uploading, setUploading] = useState(false),
    [uploadNotice, setUploadNotice] = useState('');
  const fileInput = useRef<HTMLInputElement>(null),
    uploadAbort = useRef<AbortController | null>(null);
  useEffect(() => () => uploadAbort.current?.abort(), []);
  async function upload(files: File[]) {
    if (busy || uploading || !files.length) return;
    if (
      files.length + attachments.length > 10 ||
      files.some((file) => !file.size || file.size > 20 * 1024 * 1024)
    ) {
      setUploadNotice('每条消息最多附加 10 份文件，每份需非空且最多 20 MiB。');
      return;
    }
    const abort = new AbortController();
    uploadAbort.current = abort;
    setUploading(true);
    setUploadNotice('正在保存本机附件副本。');
    try {
      for (const file of files) {
        const result = await request<{ workspace: { id: string }; path: string; task: { id: string } }>(
          `/work/upload?name=${encodeURIComponent(file.name)}`,
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/octet-stream' },
            body: file,
            signal: abort.signal,
          },
        );
        if (abort.signal.aborted) return;
        setAttachments((items) => [
          ...items,
          {
            id: result.task.id,
            name: file.name,
            workspace_id: result.workspace.id,
            path: result.path,
            bytes: file.size,
          },
        ]);
      }
      setUploadNotice('附件副本已保存。写下处理要求并发送后，瞬光才会开始任务。');
    } catch (error) {
      if (!abort.signal.aborted) setUploadNotice((error as Error).message);
    } finally {
      if (!abort.signal.aborted) setUploading(false);
    }
  }
  const threadMessages = useMemo(
    () =>
      partial === null
        ? messages
        : [
            ...messages,
            {
              id: 'current-stream',
              role: 'assistant' as const,
              content: partial,
              status: 'running' as const,
              created_at: new Date().toISOString(),
              tools,
              sources,
            },
          ],
    [messages, partial, tools, sources],
  );
  const viewport = useRef<HTMLDivElement>(null);
  const hasMessages = threadMessages.length > 0;
  useEffect(() => {
    if (!hasMessages && viewport.current) viewport.current.scrollTop = 0;
  }, [hasMessages]);
  // The server owns persistence/tools; assistant-ui intentionally owns presentation and composer.
  const runtime = useExternalStoreRuntime<Message>({
    messages: threadMessages,
    isRunning: busy,
    isLoading: loading,
    isDisabled: loading || uploading,
    convertMessage: (message): ThreadMessageLike => ({
      id: message.id,
      role: message.role,
      content: [{ type: 'text', text: message.content }],
      createdAt: new Date(message.created_at),
      ...(message.role === 'assistant'
        ? {
            status:
              message.status === 'running'
                ? { type: 'running' }
                : message.status === 'complete'
                  ? { type: 'complete', reason: 'stop' }
                  : { type: 'incomplete', reason: message.status === 'interrupted' ? 'cancelled' : 'error' },
          }
        : {}),
    }),
    onNew: async (message) => {
      const text = message.content
        .filter((part) => part.type === 'text')
        .map((part) => part.text)
        .join('\n');
      if (
        !(await onSend(
          text,
          attachments.map((item) => item.id),
        ))
      )
        runtime.thread.composer.setText(text);
      else setAttachments([]);
    },
    onCancel: async () => onStop(),
  });
  function suggestion(text: string) {
    runtime.thread.composer.setText(text);
    document.getElementById('chat-input')?.focus();
  }
  return (
    <MessagesContext.Provider value={threadMessages}>
      <AssistantRuntimeProvider runtime={runtime}>
        <ThreadPrimitive.Root
          className="thread-root"
          onDragOver={(event) => {
            if (event.dataTransfer.types.includes('Files')) event.preventDefault();
          }}
          onDrop={(event) => {
            if (event.dataTransfer.files.length) {
              event.preventDefault();
              void upload(Array.from(event.dataTransfer.files));
            }
          }}
        >
          <ThreadPrimitive.Viewport
            ref={viewport}
            className={`conversation-scroll ${hasMessages ? '' : 'welcome-scroll'}`}
            autoScroll={hasMessages}
            scrollToBottomOnInitialize={hasMessages}
            scrollToBottomOnThreadSwitch={hasMessages}
          >
            {threadMessages.length === 0 ? (
              <motion.div
                className="welcome"
                initial={{ opacity: 0, y: 14 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.6 }}
              >
                <div className="chapter-label">
                  <span /> WARM LIGHT, ALWAYS WITH YOU <span />
                </div>
                <div className="hero-orb">
                  <div className="orb-ring ring-one" />
                  <div className="orb-ring ring-two" />
                  <div className="orb-core">
                    <ResourceImage className="welcome-avatar" src={avatarUrl} alt="叶瞬光默认头像" />
                  </div>
                  <i className="orb-star">✦</i>
                  <i className="orb-star second">✧</i>
                </div>
                <div className="welcome-kicker">叶瞬光 · 暖霞拾光</div>
                <h1>
                  把今天，<em>说给我听。</em>
                </h1>
                <p className="welcome-description">
                  在喧嚣之外，留一隅温柔。
                  <br />
                  无论是小小的欢喜，还是没说出口的心事，我都在这里。
                </p>
                <div className="starter-cards">
                  {starters.map(({ icon: Icon, label, sub, text }) => (
                    <button key={label} onClick={() => suggestion(text)}>
                      <span className="starter-icon">
                        <Icon size={18} strokeWidth={1.5} />
                      </span>
                      <strong>{label}</strong>
                      <small>{sub}</small>
                      <ArrowUpRight className="starter-arrow" size={14} />
                    </button>
                  ))}
                </div>
                <div className="welcome-footnote">
                  <span className="subtle-dot" /> 资料有来处，记忆随时可管理
                </div>
              </motion.div>
            ) : (
              <div className="message-list">
                <div className="chat-date">
                  {new Date().toLocaleDateString('zh-CN', { month: 'long', day: 'numeric' })} · 拾起日常的微光
                </div>
                <ThreadPrimitive.Messages>{() => <ChatMessage />}</ThreadPrimitive.Messages>
              </div>
            )}
            <ChatFileTasks
              conversationId={conversationId}
              onSettings={onSettings}
              onWork={onWork}
              attachments={messages.flatMap((message) => message.attachments ?? [])}
            />
          </ThreadPrimitive.Viewport>
          <div className="composer-area">
            {hasMessages && (
              <ThreadPrimitive.ScrollToBottom className="scroll-bottom" aria-label="回到最新消息">
                <ArrowDown size={14} /> 最新消息
              </ThreadPrimitive.ScrollToBottom>
            )}
            {(audio.busy || audio.error) && (
              <div className="chat-playback" role="status">
                <AudioLines size={15} />
                <span>
                  {audio.error ||
                    `${audio.playing ? '播放中' : '合成中'} · ${audio.label}${audio.queued ? ` · 队列 ${audio.queued}` : ''}`}
                </span>
                {audio.busy && (
                  <button type="button" className="text-link" onClick={audio.stop}>
                    <Square size={14} />
                    停止
                  </button>
                )}
                <button type="button" className="text-link" onClick={onVoice}>
                  语音设置
                </button>
              </div>
            )}
            {!configured && !loading && (
              <button className="setup-prompt" onClick={onSettings}>
                <span>
                  <span className="subtle-dot" /> 连接模型，开启我们的第一段对话
                </span>
                <span>
                  去设置 <ArrowUpRight size={13} />
                </span>
              </button>
            )}
            <ComposerPrimitive.Root className="composer">
              <input
                ref={fileInput}
                type="file"
                multiple
                hidden
                aria-label="上传聊天附件"
                disabled={busy || uploading}
                onChange={(event) => {
                  const files = Array.from(event.target.files ?? []);
                  event.target.value = '';
                  void upload(files);
                }}
              />
              {!!attachments.length && (
                <div className="composer-attachments">
                  {attachments.map((item) => (
                    <span className="attachment-chip" key={item.id}>
                      {item.name}
                      <button
                        type="button"
                        aria-label={`移除附件 ${item.name}`}
                        disabled={uploading || busy}
                        onClick={() =>
                          setAttachments((items) => items.filter((value) => value.id !== item.id))
                        }
                      >
                        <X size={13} />
                      </button>
                    </span>
                  ))}
                </div>
              )}
              <ComposerPrimitive.Input
                id="chat-input"
                aria-label="给瞬光伴行发送消息"
                placeholder="有什么想说的？慢慢来，我在听。"
                maxLength={MAX_MESSAGE_LENGTH}
                minRows={2}
                maxRows={5}
                submitMode="enter"
                unstable_insertNewlineOnTouchEnter
                addAttachmentOnPaste={false}
                disabled={busy || uploading}
              />
              <div className="composer-bottom">
                <div className="composer-tools">
                  <button
                    type="button"
                    className="icon-button"
                    aria-label="添加文件附件"
                    title="上传文件，也可以拖入聊天"
                    disabled={busy || uploading}
                    onClick={() => fileInput.current?.click()}
                  >
                    <Paperclip size={17} />
                  </button>
                  <button
                    type="button"
                    className="icon-button"
                    onClick={onVoice}
                    aria-label="语音设置"
                    title="语音设置"
                  >
                    <AudioLines size={17} />
                  </button>
                  <button
                    type="button"
                    className="icon-button"
                    onClick={onTools}
                    aria-label="工具设置"
                    title="工具设置"
                  >
                    <Wrench size={16} />
                  </button>
                  <span className="mode-divider" />
                  <span className="composer-mode">
                    <Sparkles size={13} /> 陪伴模式
                  </span>
                </div>
                <span className="composer-right">
                  <span className="text-mode">文字对话</span>
                  {busy ? (
                    <ComposerPrimitive.Cancel className="send-button" aria-label="停止回复">
                      <Square size={15} fill="currentColor" />
                    </ComposerPrimitive.Cancel>
                  ) : (
                    <ComposerPrimitive.Send className="send-button" aria-label="发送消息">
                      <ArrowUp size={20} />
                    </ComposerPrimitive.Send>
                  )}
                </span>
              </div>
            </ComposerPrimitive.Root>
            {uploadNotice && (
              <p className="attachment-notice" role="status">
                {uploadNotice}
              </p>
            )}
            <div className="composer-caption">
              <span>Enter 发送 · Shift + Enter 换行</span>
              <span>AI 回复可能有误，请核实重要信息</span>
            </div>
          </div>
        </ThreadPrimitive.Root>
      </AssistantRuntimeProvider>
    </MessagesContext.Provider>
  );
}
