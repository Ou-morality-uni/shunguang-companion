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
  const [location, setLocation] = useState(''),
    [busy, setBusy] = useState(false);
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
      const folders = await request<Workspace[]>('/work/workspaces');
      const folder = folders.find((item) => item.id === artifact?.workspace_id);
      setLocation(
        folder
          ? `${folder.path.replace(/[\\/]$/, '')}/${artifact?.path}`
          : '原成果文件夹已不可用，请到工作台检查授权。',
      );
    } catch (error) {
      setNotice((error as Error).message);
    }
  }
  return (
    <article
      className={`file-card ${enter ? 'content-arrive' : ''}`}
      tabIndex={-1}
      aria-label={markdown ? '总结成品' : `成果：${artifact.name}`}
    >
      <strong>{artifact.name}</strong>
      <p>
        {markdown
          ? '根据本任务已读取的资料整理，包含来源和阅读范围；单独保存为新文件。'
          : '本任务已保存的新副本，原文件保留。'}
      </p>
      {artifact.validation?.calculation === 'passed' && <p className="space-note">公式已完成实际重算。</p>}
      <div className="work-actions">
        <Button ref={previewButton} variant="outline" disabled={busy} onClick={() => void load()}>
          {preview !== null || officePreview !== null
            ? '收起成果预览'
            : markdown
              ? '预览总结文件'
              : `预览成果 ${artifact.name}`}
        </Button>
        <a className="text-link" href={`/api/work/artifacts/${identity}`} download>
          {markdown ? '下载总结' : '下载成果'}
        </a>
        <Button variant="ghost" onClick={() => void showLocation()}>
          查看保存位置
        </Button>
      </div>
      {location && <p className="file-location">{location}</p>}
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
      <p>{pause?.reason}</p>
      {pause?.outline && <DocumentMarkdown text={pause.outline} />}
      {task.status === 'waiting_output' && (
        <p>检查项目 data/outputs 目录是否可写后，点击保存；无需重新总结。</p>
      )}
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
  attachments,
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
  const openResource = useResourcePreview();
  const sources = (task.context?.sources ?? []) as {
    kind: 'attachment' | 'artifact';
    id: string;
    name: string;
  }[];
  const summary = task.steps.find((step) => ['summarize', 'office'].includes(step.action))?.result;
  async function action(operation: string, approved?: boolean) {
    setBusy(true);
    setNotice('');
    try {
      await request(`/work/tasks/${task.id}/${operation}`, {
        method: 'POST',
        ...(approved === undefined ? {} : { body: JSON.stringify({ approved }) }),
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
      className={`chat-task-card ${enter ? 'content-arrive' : ''}`}
      data-status={task.status}
      aria-label={`文件任务：${task.title}`}
    >
      <div className="file-card-heading">
        <strong>{task.title}</strong>
        <span role="status">{taskStatuses[task.status]}</span>
      </div>
      {task.error && <p role="status">{task.error}</p>}
      {openResource && sources.length > 0 && (
        <div className="work-actions">
          {sources.map((source, index) => (
            <Button
              key={`${source.id}:${index}`}
              variant="outline"
              onClick={(event) =>
                openResource({ kind: source.kind, id: source.id, title: source.name }, event.currentTarget)
              }
            >
              预览来源 {source.name}
            </Button>
          ))}
        </div>
      )}
      {task.steps
        .filter((step) => step.action === 'read_document')
        .map((step, index) => (
          <div key={index}>
            <p className="space-note">
              {attachments.find((item) => item.path === step.path && item.workspace_id === task.workspace_id)
                ?.name ?? step.path}
              ：
              {typeof step.result?.coverage === 'string'
                ? step.result.coverage
                : step.state === 'complete'
                  ? '指定范围已处理'
                  : '等待或正在读取'}
            </p>
            {step.vision_request && task.status === 'waiting_vision' && (
              <VisionApproval
                taskId={task.id}
                info={step.vision_request}
                onChanged={onChanged}
                onModelSettings={onSettings}
              />
            )}
            {step.result && (
              <details>
                <summary>查看已读资料与来源</summary>
                <DocumentResult result={step.result} />
              </details>
            )}
          </div>
        ))}
      {typeof summary?.summary === 'string' && (
        <>
          <DocumentMarkdown text={summary.summary} />
          {Array.isArray(summary.warnings) && (
            <ul>
              {summary.warnings.map((warning, index) => (
                <li key={index}>{String(warning)}</li>
              ))}
            </ul>
          )}
        </>
      )}
      <ArtifactCard task={task} enter={!initiallyComplete.current} />
      {Array.isArray(summary?.annotation_results) && (
        <ul className="space-note">
          {summary.annotation_results.map((entry: { id: string; location: string; status: string }) => (
            <li key={entry.id}>
              {entry.location}：
              {entry.status === 'applied' ? '已修订该目标，请核对结果' : '已生成修订稿，请核对此项意见'}
            </li>
          ))}
        </ul>
      )}
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
            <Button disabled={busy} onClick={() => void action('approval', true)}>
              同意执行此任务（含删除）
            </Button>
            <Button variant="outline" disabled={busy} onClick={() => void action('approval', false)}>
              拒绝执行
            </Button>
          </div>
        </div>
      )}
      {['queued', 'running', 'waiting_vision'].includes(task.status) && (
        <Button variant="outline" disabled={busy} onClick={() => void action('cancel')}>
          取消文件任务
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

const TasksContext = createContext<{ tasks: FileTask[]; initial: Set<string>; onWork: () => void }>({
  tasks: [],
  initial: new Set(),
  onWork: () => {},
});

export function FileTasksProvider({
  conversationId,
  onWork,
  onTaskStatus,
  children,
}: {
  conversationId: string | null;
  onWork: () => void;
  onTaskStatus?: (status: string | null) => void;
  children: ReactNode;
}) {
  const [tasks, setTasks] = useState<FileTask[]>([]),
    [notice, setNotice] = useState('');
  const initialTasks = useRef<Set<string> | null>(null);
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
      }
    },
    [conversationId],
  );
  useEffect(() => {
    setTasks([]);
    initialTasks.current = null;
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
          setNotice((error as Error).message);
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
    <TasksContext.Provider value={{ tasks, initial: initialTasks.current ?? new Set(), onWork }}>
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
  const { tasks: records, initial, onWork } = useContext(TasksContext);
  const openResource = useResourcePreview();
  const tasks = records.filter(
    (task) =>
      all ||
      (task.context?.source_message_id
        ? task.context.source_message_id === requestId
        : taskIds.includes(task.id)),
  );
  if (!tasks.length) return null;
  return (
    <section className="chat-file-tasks compact-file-tasks" aria-label="聊天文件任务">
      {tasks.map((task) => {
        const result = task.steps.find((step) => ['summarize', 'office'].includes(step.action))?.result;
        const abstract =
          typeof result?.abstract === 'string'
            ? result.abstract
            : typeof result?.summary === 'string'
              ? result.summary.replace(/```[\s\S]*?```/g, '').slice(0, 240)
              : '';
        return (
          <article
            key={task.id}
            className={`file-task-short ${!initial.has(task.id) ? 'content-arrive' : ''}`}
          >
            <div className="file-card-heading">
              <strong>{task.title}</strong>
              <span role="status">{taskStatuses[task.status]}</span>
            </div>
            {abstract && (
              <div className="message-text task-conclusion">
                <DocumentMarkdown text={abstract} />
              </div>
            )}
            {task.error && <p role="status">{task.error.slice(0, 200)}</p>}
            <Button
              variant="outline"
              aria-label={`预览资料：${task.title}`}
              onClick={(event) => {
                let source = (
                  task.context?.sources as
                    { kind: 'attachment' | 'artifact'; id: string; name: string }[] | undefined
                )?.[0];
                if (!source) {
                  const file = attachments.find(
                    (item) =>
                      item.workspace_id === task.workspace_id &&
                      task.steps.some((step) => step.path === item.path),
                  );
                  if (file) source = { kind: 'attachment', id: file.id, name: file.name };
                }
                if (openResource)
                  openResource(
                    source
                      ? { kind: source.kind, id: source.id, title: source.name }
                      : { kind: 'task', id: task.id, title: task.title },
                    event.currentTarget,
                  );
                else onWork();
              }}
            >
              预览资料
            </Button>
            <button
              type="button"
              className="text-button"
              aria-label={`任务详情：${task.title}`}
              onClick={(event) =>
                openResource
                  ? openResource({ kind: 'task', id: task.id, title: task.title }, event.currentTarget)
                  : onWork()
              }
            >
              状态与操作
            </button>
            <ArtifactCard task={task} />
          </article>
        );
      })}
    </section>
  );
}
