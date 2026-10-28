import {
  lazy,
  Suspense,
  createContext,
  useContext,
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import { Button } from '@/components/ui/button';
import { ContextMenu, DropdownMenu } from 'radix-ui';
import { ArrowDown, FileText, MoreVertical } from 'lucide-react';
import { request, type Attachment, type FileTask, type Workspace } from './api';
import { DocumentResult, VisionApproval } from './DocumentControls';
import { useResourcePreview } from './PreviewContext';
import { DocumentMarkdown } from './DocumentMarkdown';

const StandaloneResourcePreview = lazy(() =>
  import('./ResourcePreview').then((module) => ({ default: module.ResourcePreview })),
);

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

export function OutputFolder() {
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [notice, setNotice] = useState('');
  useEffect(() => {
    const abort = new AbortController();
    void request<{ workspace: Workspace | null }>('/work/output', { signal: abort.signal })
      .then((result) => {
        if (!abort.signal.aborted) setWorkspace(result.workspace);
      })
      .catch((error) => {
        if (!abort.signal.aborted) setNotice((error as Error).message);
      });
    return () => abort.abort();
  }, []);
  return (
    <div className="file-output-folder">
      <p>
        {workspace?.enabled
          ? `当前成果目录：${workspace.path}`
          : '成果默认保存到项目 data/outputs，每次任务单独建立文件夹。'}
      </p>
      {notice && <p role="status">{notice}</p>}
    </div>
  );
}

export function AttachmentCard({ attachment }: { attachment: Attachment }) {
  const openResource = useResourcePreview();
  const [open, setOpen] = useState(false);
  return (
    <article className="file-card" tabIndex={-1} aria-label={`附件：${attachment.name}`}>
      <div className="file-card-heading">
        <strong>{attachment.name}</strong>
        <span>{Math.ceil(attachment.bytes / 1024)} KiB · 本机副本</span>
      </div>
      <div className="work-actions">
        <Button
          variant="outline"
          aria-label={`预览 ${attachment.name}`}
          onClick={(event) => {
            if (openResource)
              openResource(
                { kind: 'attachment', id: attachment.id, title: attachment.name },
                event.currentTarget,
              );
            else setOpen(!open);
          }}
        >
          {open ? '收起预览' : '预览'}
        </Button>
      </div>
      {open && (
        <div className="standalone-preview">
          <Suspense fallback={<p role="status">正在准备预览…</p>}>
            <StandaloneResourcePreview
              resource={{ kind: 'attachment', id: attachment.id, title: attachment.name }}
            />
          </Suspense>
        </div>
      )}
    </article>
  );
}

type SavedArtifact = {
  name: string;
  path: string;
  workspace_id: string;
  sha256?: string;
  validation?: Record<string, unknown>;
};

export function ArtifactCard({ task, enter = false }: { task: FileTask; enter?: boolean }) {
  const artifacts = (task.context?.artifacts ??
    (task.context?.artifact ? [task.context.artifact] : [])) as SavedArtifact[];
  return (
    <>
      {artifacts.map((artifact, index) => (
        <SavedArtifactCard
          key={artifact.path}
          artifact={artifact}
          identity={task.id + (index ? `~${index}` : '')}
          enter={enter}
        />
      ))}
    </>
  );
}

function SavedArtifactCard({
  artifact,
  identity,
  enter,
}: {
  artifact: SavedArtifact;
  identity: string;
  enter: boolean;
}) {
  const openResource = useResourcePreview();
  const previewButton = useRef<HTMLButtonElement>(null);
  const markdown = /\.(md|txt)$/i.test(artifact.name);
  const [officePreview, setOfficePreview] = useState<Record<string, unknown> | null>(null);
  const [preview, setPreview] = useState<string | null>(null),
    [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [thumbnailFailed, setThumbnailFailed] = useState(false);
  async function load() {
    if (openResource) {
      openResource({ kind: 'artifact', id: identity, title: artifact.name }, previewButton.current);
      return;
    }
    if (preview !== null || officePreview !== null) {
      setPreview(null);
      setOfficePreview(null);
      return;
    }
    setBusy(true);
    setNotice('');
    try {
      if (markdown) {
        const response = await fetch(`/api/work/artifacts/${identity}`);
        if (!response.ok)
          throw new Error('成果文件暂不可读取，可能已被移动、修改或撤销授权；请查看保存位置。');
        setPreview(await response.text());
      } else setOfficePreview(await request(`/work/artifacts/${identity}/preview`));
    } catch (error) {
      setNotice((error as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function showLocation() {
    try {
      const version =
        artifact.sha256 ??
        (await request<{ version: string }>(`/work/resources/artifact/${identity}/targets`)).version;
      await request(`/work/artifacts/${identity}/reveal`, {
        method: 'POST',
        body: JSON.stringify({ version }),
      });
      setNotice('已在文件管理器中定位。');
    } catch (error) {
      setNotice((error as Error).message);
    }
  }
  return (
    <ContextMenu.Root>
      <ContextMenu.Trigger asChild>
        <article
          className={`file-card artifact-tile ${enter ? 'content-arrive' : ''}`}
          tabIndex={-1}
          aria-label={markdown ? '总结成品' : `成果：${artifact.name}`}
        >
          <div className="artifact-thumbnail" aria-label="成果缩图">
            {artifact.sha256 && !markdown && !thumbnailFailed ? (
              <img
                loading="lazy"
                alt={`${artifact.name} 首屏缩图`}
                src={`/api/work/artifacts/${encodeURIComponent(identity)}/thumbnail?version=${artifact.sha256}`}
                onError={() => setThumbnailFailed(true)}
              />
            ) : (
              <FileText size={30} aria-label="文件类型图标" />
            )}
          </div>
          <div className="artifact-copy">
            <strong title={artifact.name}>{artifact.name}</strong>
            {artifact.validation?.calculation === 'passed' && <small>公式已完成实际重算</small>}
            <div className="work-actions">
              <Button
                ref={previewButton}
                variant="outline"
                disabled={busy}
                onClick={() => void load()}
                aria-label={
                  preview !== null || officePreview !== null
                    ? '收起成果预览'
                    : markdown
                      ? '预览总结文件'
                      : `预览成果 ${artifact.name}`
                }
              >
                {preview !== null || officePreview !== null ? '收起预览' : '预览'}
              </Button>
              <a
                className="text-link artifact-download"
                href={`/api/work/artifacts/${identity}`}
                download
                aria-label={markdown ? '下载总结' : '下载成果'}
                title="下载"
              >
                <ArrowDown size={17} />
              </a>
              <DropdownMenu.Root>
                <DropdownMenu.Trigger asChild>
                  <button type="button" className="icon-button" aria-label={`成果操作 ${artifact.name}`}>
                    <MoreVertical size={16} />
                  </button>
                </DropdownMenu.Trigger>
                <DropdownMenu.Portal>
                  <DropdownMenu.Content className="annotation-menu" sideOffset={4}>
                    <DropdownMenu.Item onSelect={() => void showLocation()}>查看位置</DropdownMenu.Item>
                  </DropdownMenu.Content>
                </DropdownMenu.Portal>
              </DropdownMenu.Root>
            </div>
          </div>
          {notice && <p role="status">{notice}</p>}
          {preview !== null && (
            <div className="standalone-preview">
              <DocumentMarkdown text={preview} />
            </div>
          )}
          {officePreview !== null && (
            <div className="standalone-preview">
              <DocumentResult result={officePreview} />
            </div>
          )}
        </article>
      </ContextMenu.Trigger>
      <ContextMenu.Portal>
        <ContextMenu.Content className="annotation-menu">
          <ContextMenu.Item onSelect={() => void showLocation()}>查看位置</ContextMenu.Item>
        </ContextMenu.Content>
      </ContextMenu.Portal>
    </ContextMenu.Root>
  );
}

export function ContinueTask({ task, onChanged }: { task: FileTask; onChanged: () => Promise<void> }) {
  const [busy, setBusy] = useState(false),
    [notice, setNotice] = useState('');
  if (!['waiting_limit', 'waiting_output'].includes(task.status)) return null;
  const pause = task.context?.pause as { reason?: string; kind?: string; outline?: string } | undefined;
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
      <p>
        {pause?.kind === 'overwrite' || pause?.kind === 'outline'
          ? pause.reason
          : task.status === 'waiting_output'
            ? '内容已经整理好了，暂时没能保存文件。'
            : '这份资料还没读完，要继续吗？'}
      </p>
      {pause?.outline && <DocumentMarkdown text={pause.outline} />}
      <div className="work-actions">
        <Button disabled={busy} onClick={() => void decide(true)}>
          {pause?.kind === 'overwrite'
            ? '确认覆盖并保留备份'
            : pause?.kind === 'outline'
              ? '确认提纲并制作'
              : task.status === 'waiting_output'
                ? '重新保存成果'
                : '继续下一轮处理'}
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
          {task.error.includes('PDF') && task.error.includes('排版')
            ? '这份 PDF 暂时不能在保留排版的情况下可靠修改。'
            : task.can_retry_summary
              ? '这次没读完，可以再试一次。'
              : '这次没能处理好，我先停下了。'}
        </p>
      )}
      {task.status === 'interrupted' && <p role="status">刚才的文件处理被打断了。</p>}
      {task.status === 'cancelled' && <p role="status">已经停下了。</p>}
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
      {task.status === 'waiting_approval' && (
        <div className="work-approval" role="group" aria-label="删除授权">
          <p>本任务包含删除，尚未执行。请核对全部操作，授权只适用于这份清单。</p>
          <ul>
            {task.steps.map((step, index) => (
              <li key={index}>
                {step.action}：{step.path}
                {step.destination ? ` → ${step.destination}` : ''}
              </li>
            ))}
          </ul>
          <div className="work-actions">
            <Button disabled={busy} onClick={() => void action('approval', { approved: true })}>
              同意执行此任务（含删除）
            </Button>
            <Button
              variant="outline"
              disabled={busy}
              onClick={() => void action('approval', { approved: false })}
            >
              拒绝执行
            </Button>
          </div>
        </div>
      )}
      {['queued', 'running', 'waiting_vision'].includes(task.status) && (
        <Button variant="outline" disabled={busy} onClick={() => void action('cancel')}>
          先停下
        </Button>
      )}
      {task.can_restore && (
        <Button variant="outline" disabled={busy} onClick={() => void action('restore')}>
          恢复本次文件修改
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
    async function poll() {
      if (polling || denied || abort.signal.aborted || document.hidden) return;
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
    return () => {
      abort.abort();
      clearInterval(timer);
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
