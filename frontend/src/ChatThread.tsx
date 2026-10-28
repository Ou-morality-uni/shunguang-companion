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
import remarkGfm from 'remark-gfm';
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
  Square,
  Wrench,
  Paperclip,
  X,
} from 'lucide-react';
import {
  avatarUrl,
  request,
  type Attachment,
  type Message,
  type ModelChoice,
  type ModelSettings,
  type Features,
  type Source,
  type ToolEvent,
} from './api';
import { ModelPicker } from './ModelPicker';
import { VoiceInput } from './VoiceInput';
import { AttachmentCard, FileTasksProvider, MessageFileTasks } from './FileTasks';
import { Sources } from './Evidence';
import { useCompanionAudio } from './useAudioQueue';
import { ResourceImage } from './ResourceImage';
import { MessageSticker } from './MessageSticker';
import { MAX_MESSAGE_LENGTH } from './generated/limits';
import { visibleAssistantText } from './replyText';
import {
  AnnotationTarget,
  AnnotationTray,
  ReplyAnnotations,
  useAnnotations,
  type AnnotationSubmission,
  type AnnotationAnchor,
} from './Annotations';
const MarkdownText = () => <MarkdownTextPrimitive defer smooth remarkPlugins={[remarkGfm]} />;
const MessagesContext = createContext<Message[]>([]);
const HistoryContext = createContext<Set<string>>(new Set());

const starters = [
  {
    icon: MessageSquare,
    label: '聊聊今天',
    sub: '分享日常，也听听你的心事',
    text: '今天有点累，想和你聊一会儿。',
  },
  {
    icon: Paperclip,
    label: '总结资料',
    sub: '附上文件，一起梳理重点',
    text: '帮我总结这份资料，梳理重点，并注明对应位置。',
  },
  { icon: BookOpen, label: '世界漫游', sub: '聊聊新艾利都的故事', text: '你现在知道哪些关于绝区零的设定？' },
];

function ChatMessage() {
  const message = useAuiState((state) => state.message);
  const user = message.role === 'user';
  const messages = useContext(MessagesContext);
  const record = messages.find((item) => item.id === message.id);
  const position = messages.findIndex((item) => item.id === message.id);
  const before = messages.slice(0, position < 0 ? messages.length : position);
  const requestIndex = before.map((item) => item.role).lastIndexOf('user');
  const requestId =
    !user && !before.slice(requestIndex + 1).some((item) => item.role === 'assistant')
      ? before[requestIndex]?.id
      : undefined;
  const taskIds = (record?.tools ?? []).flatMap((item) => {
    const result = item.result as { task?: { id?: string } } | undefined;
    return ['workspace_files', 'office_files'].includes(item.name ?? '') && result?.task?.id
      ? [result.task.id]
      : [];
  });
  const audio = useCompanionAudio();
  const history = useContext(HistoryContext);
  const enter = !history.has(message.id) && (user || message.status?.type === 'running');
  return (
    <MessagePrimitive.Root className={`message ${user ? 'user' : 'assistant'}`}>
      <motion.div
        className="message-layout"
        initial={enter ? { opacity: 0, y: 6 } : false}
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
            {!user && record?.status === 'complete' ? (
              <AnnotationTarget
                label="这条回复"
                messageId={message.id}
                prepare={async () => {
                  const value = await request<{ version: string }>(
                    `/work/resources/message/${encodeURIComponent(message.id)}/targets`,
                  );
                  return {
                    source: { kind: 'message', id: message.id, version: value.version },
                    target_id: 'message',
                    name: '小光的回复',
                    location: '聊天回复',
                  } satisfies AnnotationAnchor;
                }}
              >
                <MessagePrimitive.Parts components={{ Text: MarkdownText }} />
              </AnnotationTarget>
            ) : (
              <MessagePrimitive.Parts components={{ Text: MarkdownText }} />
            )}
            {message.content.every((part) => part.type === 'text' && !part.text) && (
              <span className="thinking">
                正在组织语言<span>…</span>
              </span>
            )}
          </div>
          {!user && record?.status === 'complete' && record.sticker && (
            <MessageSticker key={record.sticker.id} sticker={record.sticker} />
          )}
          <ReplyAnnotations items={record?.annotations} />
          {record?.attachments?.map((attachment) => (
            <AttachmentCard key={attachment.id} attachment={attachment} />
          ))}
          <Sources sources={record?.sources} />
          {!user && (
            <MessageFileTasks
              requestId={requestId}
              taskIds={taskIds}
              attachments={before[requestIndex]?.attachments ?? []}
            />
          )}
          <ActionBarPrimitive.Root className="message-actions">
            <ActionBarPrimitive.Copy className="copy-button" aria-label="复制消息">
              <Copy size={13} />
              <span className="copy-label">复制</span>
              <span className="copied-label">已复制</span>
            </ActionBarPrimitive.Copy>
            {!user && record?.content && message.status?.type !== 'running' && (
              <button
                className="copy-button"
                onClick={() => audio.enqueue(visibleAssistantText(record.content))}
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
  modelSettings?: ModelSettings | null;
  asrSettings?: Features['asr'];
  tools?: ToolEvent[];
  sources?: Source[];
  onSend: (
    text: string,
    attachments?: string[],
    modelChoice?: ModelChoice,
    annotations?: AnnotationSubmission,
  ) => Promise<boolean>;
  onStop: () => void;
  onSettings: () => void;
  onVoice: () => void;
  onTools: () => void;
  conversationId: string | null;
  onTaskStatus?: (status: string | null) => void;
  onTaskReply?: () => Promise<boolean>;
  onWork: () => void;
};

export function ChatThread({
  messages,
  partial,
  busy,
  loading,
  configured,
  modelSettings,
  asrSettings,
  tools,
  sources,
  onSend,
  onStop,
  onSettings,
  onVoice,
  onTools,
  conversationId,
  onTaskStatus,
  onTaskReply,
  onWork,
}: Props) {
  const audio = useCompanionAudio();
  const annotations = useAnnotations();
  const [modelChoice, setModelChoice] = useState<ModelChoice>();
  const [voiceBusy, setVoiceBusy] = useState(false);
  const history = useRef(new Set(messages.map((message) => message.id)));
  const historyReady = useRef(!loading);
  if (!historyReady.current) {
    messages.forEach((message) => history.current.add(message.id));
    if (!loading) historyReady.current = true;
  }
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
      content: [
        {
          type: 'text',
          text: message.role === 'assistant' ? visibleAssistantText(message.content) : message.content,
        },
      ],
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
      if (voiceBusy) {
        runtime.thread.composer.setText(text);
        return;
      }
      let submission: AnnotationSubmission | undefined;
      try {
        submission = await annotations?.submission();
      } catch (error) {
        setUploadNotice((error as Error).message);
        runtime.thread.composer.setText(text);
        return;
      }
      annotations?.setSending(true);
      try {
        const accepted = submission
          ? await onSend(
              text || '请按这些批注修改。',
              attachments.map((item) => item.id),
              modelChoice,
              submission,
            )
          : await onSend(
              text,
              attachments.map((item) => item.id),
              modelChoice,
            );
        if (!accepted) runtime.thread.composer.setText(text);
        else {
          setAttachments([]);
          if (submission) annotations?.submitted(submission.ids);
        }
      } finally {
        annotations?.setSending(false);
      }
    },
    onCancel: async () => onStop(),
  });
  useEffect(() => {
    if (annotations?.drafts.length && !runtime.thread.composer.getState().text.trim()) {
      runtime.thread.composer.setText('请按这些批注修改。');
    }
  }, [annotations?.drafts.length, conversationId, runtime]);
  function suggestion(text: string) {
    runtime.thread.composer.setText(text);
    document.getElementById('chat-input')?.focus();
  }
  return (
    <MessagesContext.Provider value={threadMessages}>
      <HistoryContext.Provider value={history.current}>
        <AssistantRuntimeProvider runtime={runtime}>
          <FileTasksProvider
            conversationId={conversationId}
            onWork={onWork}
            onTaskStatus={onTaskStatus}
            onReply={onTaskReply}
            onSettings={onSettings}
          >
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
                    initial={{ opacity: 0, y: 6 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.25 }}
                  >
                    <ResourceImage className="welcome-portrait" src={avatarUrl} alt="叶瞬光默认头像" />
                    <div className="welcome-kicker">叶瞬光 · 暖霞拾光</div>
                    <h1>
                      把今天，<em>说给我听。</em>
                    </h1>
                    <p className="welcome-description">聊聊今天，或附上一份资料。我们一起慢慢理清。</p>
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
                      {new Date().toLocaleDateString('zh-CN', { month: 'long', day: 'numeric' })} ·
                      拾起日常的微光
                    </div>
                    <ThreadPrimitive.Messages>{() => <ChatMessage />}</ThreadPrimitive.Messages>
                  </div>
                )}
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
                {!configured && !modelChoice && !loading && (
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
                  <AnnotationTray />
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
                    minRows={1}
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
                        disabled={busy || uploading || voiceBusy}
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
                    </div>
                    <span className="composer-right">
                      <ModelPicker
                        conversationId={conversationId}
                        disabled={busy || loading || uploading || voiceBusy}
                        onChange={setModelChoice}
                        onSettings={onSettings}
                        revision={modelSettings}
                      />
                      <VoiceInput
                        settings={asrSettings}
                        composer={runtime.thread.composer}
                        disabled={busy || loading || uploading}
                        onSettings={onVoice}
                        onBusyChange={setVoiceBusy}
                      />
                      {busy ? (
                        <ComposerPrimitive.Cancel className="send-button" aria-label="停止回复">
                          <Square size={15} fill="currentColor" />
                        </ComposerPrimitive.Cancel>
                      ) : (
                        <ComposerPrimitive.Send
                          className="send-button"
                          aria-label="发送消息"
                          disabled={voiceBusy}
                        >
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
          </FileTasksProvider>
        </AssistantRuntimeProvider>
      </HistoryContext.Provider>
    </MessagesContext.Provider>
  );
}
