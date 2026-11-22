import { createContext, useContext, useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { ImageViewer } from './ImageViewer';
import { Button } from '@/components/ui/button';
import { FileText } from 'lucide-react';
import { request, type Attachment, type FileTask } from './api';
import { VisionApproval } from './DocumentControls';

export const taskStatuses: Record<FileTask['status'], string> = {
  queued: '排队中',
  running: '执行中',
  waiting_approval: '等待删除授权',
  waiting_vision: '等待图像识别授权',
  waiting_limit: '等待确认继续',
  waiting_output: '等待恢复成果目录',
  complete: '已完成',
  failed: '已停止：发生错误',
  cancelled: '已取消',
  interrupted: '服务重启后中断',
  restoring: '恢复中',
  restored: '已恢复',
};

export { DocumentMarkdown } from './DocumentMarkdown';

export function AttachmentPreview({
  attachment,
  thumbnail = false,
  imageOnly = false,
}: {
  attachment: Attachment;
  thumbnail?: boolean;
  imageOnly?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState('');
  const dialog = useRef<HTMLDialogElement>(null);
  const url = '/api/work/files/' + encodeURIComponent(attachment.id);
  const image = /\.(png|jpe?g|webp|gif|bmp|tiff?)$/i.test(attachment.name);
  useEffect(() => {
    if (!open) return;
    dialog.current?.showModal();
    if (image) return;
    const controller = new AbortController();
    setText('正在读取预览…');
    request<{ text: string; warnings: string[] }>(url + '/preview', { signal: controller.signal })
      .then((result) =>
        setText([result.text, ...result.warnings].filter(Boolean).join('\n') || '此附件没有可预览的文字。'),
      )
      .catch((error) => {
        if (!controller.signal.aborted) setText(error.message);
      });
    return () => controller.abort();
  }, [open, image, url]);
  return (
    <>
      <button
        type="button"
        className={imageOnly ? 'sent-image' : 'attachment-preview-trigger'}
        aria-label={'预览 ' + attachment.name}
        onClick={() => setOpen(true)}
      >
        {(thumbnail || imageOnly) && image && <img src={url + '/preview'} alt="" />}{' '}
        {!imageOnly && (thumbnail ? attachment.name : '预览')}
      </button>
      {open && (
        <dialog
          className={'attachment-drawer' + (image ? ' picture-drawer' : '')}
          ref={dialog}
          aria-label={'附件预览 ' + attachment.name}
          onClose={() => setOpen(false)}
        >
          <header>
            <strong>{attachment.name}</strong>
            <button type="button" onClick={() => dialog.current?.close()}>
              关闭
            </button>
          </header>
          {image ? (
            <ImageViewer src={url + '/preview?full_size=true'} name={attachment.name} />
          ) : (
            <pre>{text}</pre>
          )}
        </dialog>
      )}
    </>
  );
}

export function AttachmentCard({ attachment }: { attachment: Attachment }) {
  if (/\.(png|jpe?g|webp|gif|bmp|tiff?)$/i.test(attachment.name))
    return <AttachmentPreview attachment={attachment} imageOnly />;
  return (
    <article className="file-card" aria-label={`附件：${attachment.name}`}>
      <div className="file-card-heading">
        <strong>{attachment.name}</strong>
        <span>{Math.ceil(attachment.bytes / 1024)} KiB · 本机副本</span>
      </div>
      <AttachmentPreview attachment={attachment} />
    </article>
  );
}

type SavedArtifact = { name: string; path: string };

export function ArtifactCard({ task, enter = false }: { task: FileTask; enter?: boolean }) {
  const artifacts = (task.context?.artifacts ??
    (task.context?.artifact ? [task.context.artifact] : [])) as SavedArtifact[];
  return (
    <>
      {artifacts.map((artifact, index) => (
        <article key={artifact.path} className={`file-card ${enter ? 'content-arrive' : ''}`}>
          <FileText size={16} aria-hidden="true" />
          <strong>{artifact.name}</strong>
          <a
            className="text-link"
            href={`/api/work/artifacts/${encodeURIComponent(index ? `${task.id}~${index}` : task.id)}`}
            download
          >
            下载成果
          </a>
        </article>
      ))}
    </>
  );
}

export function ContinueTask({ task, onChanged }: { task: FileTask; onChanged: () => Promise<void> }) {
  const [busy, setBusy] = useState(false),
    [notice, setNotice] = useState('');
  if (task.status !== 'waiting_limit') return null;
  async function decide(approved: boolean) {
    setBusy(true);
    setNotice('');
    try {
      await request(`/work/tasks/${task.id}/continue`, {
        method: 'POST',
        body: JSON.stringify({ approved }),
      });
      await onChanged();
    } catch (error) {
      setNotice((error as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="work-approval" role="group" aria-label="任务继续确认">
      <p>这份资料还没读完，要继续吗？</p>
      <div className="work-actions">
        <Button disabled={busy} onClick={() => void decide(true)}>
          继续下一轮处理
        </Button>
        <Button variant="outline" disabled={busy} onClick={() => void decide(false)}>
          取消任务并保留记录
        </Button>
      </div>
      {notice && <p role="status">{notice}</p>}
    </div>
  );
}

export function TaskDetails({
  task,
  enter,
  onChanged,
  onSettings,
  attachments: _attachments,
}: {
  task: FileTask;
  enter: boolean;
  onChanged: () => Promise<void>;
  onSettings: () => void;
  attachments: Attachment[];
}) {
  const [busy, setBusy] = useState(false),
    [notice, setNotice] = useState('');
  const initiallyComplete = useRef(task.status === 'complete');
  async function action(operation: string, body?: { approved?: boolean; extend_timeout?: boolean }) {
    setBusy(true);
    setNotice('');
    try {
      await request(`/work/tasks/${task.id}/${operation}`, {
        method: 'POST',
        ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      });
      await onChanged();
    } catch (error) {
      setNotice((error as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <article
      className={`chat-task-card natural-file-feedback ${enter ? 'content-arrive' : ''}`}
      data-status={task.status}
      aria-label="文件处理"
    >
      {['queued', 'running'].includes(task.status) && <p role="status">我正在处理，稍等一下。</p>}
      {task.status === 'failed' && (
        <p role="status">
          {task.can_retry_vision
            ? task.error.startsWith('识图失败')
              ? task.error
              : '识图失败：' + task.error
            : task.error.includes('扫描版 PDF')
              ? task.error
              : task.can_retry_summary
                ? '这次没读完，可以再试一次。'
                : '这次没能处理好，我先停下了。'}
        </p>
      )}
      {task.status === 'interrupted' && <p role="status">刚才的文件处理被打断了。</p>}
      {task.status === 'cancelled' && <p role="status">已经停下了。</p>}
      {task.can_retry_vision && (
        <Button variant="outline" disabled={busy} onClick={() => void action('retry-vision')}>
          重新识图
        </Button>
      )}
      {task.can_retry_summary && (
        <Button
          variant="outline"
          disabled={busy}
          onClick={() => void action('retry-summary', { extend_timeout: true })}
        >
          再试一次
        </Button>
      )}
      {task.status === 'waiting_vision' &&
        task.steps
          .filter((step) => step.vision_request)
          .map((step, index) => (
            <VisionApproval
              key={index}
              taskId={task.id}
              info={step.vision_request!}
              onChanged={onChanged}
              onModelSettings={onSettings}
            />
          ))}
      <ArtifactCard task={task} enter={!initiallyComplete.current} />
      <ContinueTask task={task} onChanged={onChanged} />
      {['queued', 'running', 'waiting_vision'].includes(task.status) && (
        <Button variant="outline" disabled={busy} onClick={() => void action('cancel')}>
          先停下
        </Button>
      )}
      {notice && <p role="status">{notice}</p>}
    </article>
  );
}

const TasksContext = createContext<{
  tasks: FileTask[];
  initial: Set<string>;
  refresh: () => Promise<void>;
  onSettings: () => void;
}>({
  tasks: [],
  initial: new Set(),
  onSettings: () => {},
  refresh: async () => {},
});

export function FileTasksProvider({
  conversationId,
  onWork,
  onTaskStatus,
  onReply,
  onSettings,
  children,
}: {
  conversationId: string | null;
  onWork: () => void;
  onTaskStatus?: (status: string | null) => void;
  onReply?: () => Promise<boolean>;
  onSettings?: () => void;
  children: ReactNode;
}) {
  const [tasks, setTasks] = useState<FileTask[]>([]),
    [notice, setNotice] = useState('');
  const initialTasks = useRef<Set<string> | null>(null);
  const delivered = useRef(new Set<string>());
  const activeTasks = useRef(true);
  useEffect(() => {
    const current =
      tasks.find((task) =>
        [
          'queued',
          'running',
          'waiting_approval',
          'waiting_vision',
          'waiting_limit',
          'waiting_output',
        ].includes(task.status),
      ) ?? tasks[0];
    onTaskStatus?.(current ? `文件任务 · ${taskStatuses[current.status]}` : null);
  }, [tasks, onTaskStatus]);
  const refresh = useCallback(
    async (signal?: AbortSignal) => {
      if (!conversationId) return;
      const result = await request<FileTask[]>(
        `/work/tasks?conversation_id=${encodeURIComponent(conversationId)}&compact=true`,
        { signal },
      );
      if (!signal?.aborted) {
        if (initialTasks.current === null)
          initialTasks.current = new Set((Array.isArray(result) ? result : []).map((task) => task.id));
        setTasks(Array.isArray(result) ? result : []);
        activeTasks.current =
          Array.isArray(result) && result.some((task) => ['queued', 'running'].includes(task.status));
        setNotice('');
        const replies = (Array.isArray(result) ? result : []).flatMap((task) =>
          typeof task.context?.reply_message_id === 'string' &&
          !delivered.current.has(task.context.reply_message_id)
            ? [task.context.reply_message_id]
            : [],
        );
        if (replies.length && onReply && (await onReply()) && !signal?.aborted)
          replies.forEach((id) => delivered.current.add(id));
      }
    },
    [conversationId, onReply],
  );
  useEffect(() => {
    setTasks([]);
    initialTasks.current = null;
    delivered.current = new Set();
    const abort = new AbortController();
    let polling = false,
      denied = false;
    let lastPoll: number | null = null;
    async function poll(force = false) {
      if (polling || denied || abort.signal.aborted || document.hidden) return;
      if (!force && !activeTasks.current && lastPoll !== null && Date.now() - lastPoll < 15000) return;
      lastPoll = Date.now();
      polling = true;
      try {
        await refresh(abort.signal);
      } catch (error) {
        if (!abort.signal.aborted) {
          setNotice('暂时没能更新文件进度。');
          if (String((error as Error).message).includes('仅供')) denied = true;
        }
      } finally {
        polling = false;
      }
    }
    void poll();
    const timer = window.setInterval(() => void poll(), 1500);
    const changed = () => void poll(true);
    window.addEventListener('shunguang-work-updated', changed);
    return () => {
      abort.abort();
      clearInterval(timer);
      window.removeEventListener('shunguang-work-updated', changed);
    };
  }, [refresh]);
  return (
    <TasksContext.Provider
      value={{ tasks, initial: initialTasks.current ?? new Set(), refresh, onSettings: onSettings ?? onWork }}
    >
      {children}
      {notice && (
        <p className="space-note" role="status">
          {notice}
        </p>
      )}
    </TasksContext.Provider>
  );
}

export function ChatFileTasks(props: {
  conversationId: string | null;
  onWork: () => void;
  onSettings: () => void;
  onTaskStatus?: (status: string | null) => void;
}) {
  return (
    <FileTasksProvider {...props}>
      <MessageFileTasks all />
    </FileTasksProvider>
  );
}

export function MessageFileTasks({
  requestId,
  taskIds = [],
  attachments = [],
  all = false,
}: {
  requestId?: string;
  taskIds?: string[];
  attachments?: Attachment[];
  all?: boolean;
}) {
  const { tasks: records, initial, refresh, onSettings } = useContext(TasksContext);
  const tasks = records.filter(
    (task) =>
      (all ||
        (task.context?.source_message_id
          ? task.context.source_message_id === requestId
          : taskIds.includes(task.id))) &&
      (task.status !== 'complete' ||
        task.context?.artifact ||
        (task.context?.artifacts as unknown[])?.length),
  );
  if (!tasks.length) return null;
  return (
    <section className="chat-file-tasks compact-file-tasks" aria-label="文件处理反馈">
      {tasks.map((task) => (
        <TaskDetails
          key={task.id}
          task={task}
          enter={!initial.has(task.id)}
          onChanged={refresh}
          onSettings={onSettings}
          attachments={attachments}
        />
      ))}
    </section>
  );
}
