import { useCallback, useEffect, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { request, safeSourceUrl, type Attachment, type FileTask, type Workspace } from './api';
import { DocumentResult, VisionApproval } from './DocumentControls';

export const taskStatuses: Record<FileTask['status'], string> = {
  queued: '排队中',
  running: '执行中',
  waiting_approval: '等待删除授权',
  waiting_vision: '等待图像识别授权',
  waiting_limit: '等待确认继续',
  waiting_output: '等待选择成果目录',
  complete: '已完成',
  failed: '已停止：发生错误',
  cancelled: '已取消',
  interrupted: '服务重启后中断',
  restoring: '恢复中',
  restored: '已恢复',
};

export function DocumentMarkdown({ text }: { text: string }) {
  return (
    <div className="document-markdown">
      <ReactMarkdown
        components={{
          img: ({ alt }) => <span>〔图片：{alt || '请查看原文件'}〕</span>,
          a: ({ href, children }) => (
            <a href={safeSourceUrl(href)} target="_blank" rel="noopener noreferrer">
              {children}
            </a>
          ),
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}

export function OutputFolder() {
  const [workspace, setWorkspace] = useState<Workspace | null>(null),
    [path, setPath] = useState('');
  const [busy, setBusy] = useState(false),
    [notice, setNotice] = useState('');
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
  async function choose() {
    setBusy(true);
    setNotice('');
    try {
      const result = await request<{ workspace: Workspace }>('/work/output', {
        method: 'POST',
        body: JSON.stringify({ path }),
      });
      setWorkspace(result.workspace);
      setPath('');
      setNotice('成果目录已授权，以后按任务建立独立子文件夹保存。');
    } catch (error) {
      setNotice((error as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="file-output-folder">
      <p>
        {workspace?.enabled
          ? `当前成果目录：${workspace.path}`
          : '首次使用请选择已有的成果文件夹；之后每次任务会单独保存。'}
      </p>
      <details open={!workspace?.enabled}>
        <summary>{workspace?.enabled ? '更换成果文件夹' : '选择成果文件夹'}</summary>
        <label className="field">
          成果文件夹路径（本机已有文件夹）
          <Input
            value={path}
            onChange={(event) => setPath(event.target.value)}
            placeholder="粘贴文件夹的完整路径"
          />
        </label>
        <Button disabled={busy || !path.trim()} onClick={() => void choose()}>
          授权并设为成果目录
        </Button>
      </details>
      {notice && <p role="status">{notice}</p>}
    </div>
  );
}

export function AttachmentCard({ attachment }: { attachment: Attachment }) {
  const [open, setOpen] = useState(false),
    [preview, setPreview] = useState<Record<string, unknown> | null>(null);
  const [notice, setNotice] = useState(''),
    [busy, setBusy] = useState(false),
    [page, setPage] = useState(1);
  const pdf = /\.pdf$/i.test(attachment.name),
    image = /\.(png|jpe?g|webp|bmp|tiff?|gif)$/i.test(attachment.name);
  async function load(start = 1) {
    setBusy(true);
    setNotice('');
    try {
      setPreview(await request(`/work/files/${attachment.id}/preview?start=${start}`));
      setOpen(true);
    } catch (error) {
      setNotice((error as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <article className="file-card" aria-label={`附件：${attachment.name}`}>
      <div className="file-card-heading">
        <strong>{attachment.name}</strong>
        <span>{Math.ceil(attachment.bytes / 1024)} KiB · 本机副本</span>
      </div>
      <div className="work-actions">
        <Button
          variant="outline"
          disabled={busy}
          onClick={() => {
            if (open) setOpen(false);
            else if (preview) setOpen(true);
            else void load();
          }}
        >
          {open ? '收起预览' : `预览 ${attachment.name}`}
        </Button>
        <a className="text-link" href={`/api/work/files/${attachment.id}`} download>
          下载原文件副本
        </a>
      </div>
      {notice && <p role="status">{notice}</p>}
      {open && (
        <div className="file-preview">
          {(image || pdf) && (
            <img
              loading="lazy"
              src={`/api/work/files/${attachment.id}/image?page=${page}`}
              alt={pdf ? `${attachment.name} 第 ${page} 页` : attachment.name}
            />
          )}
          {pdf && (
            <label className="field">
              预览页码
              <Input
                type="number"
                min={1}
                max={Number(preview?.total_units ?? 1)}
                value={page}
                onChange={(event) =>
                  setPage(
                    Math.max(1, Math.min(Number(preview?.total_units ?? 1), Number(event.target.value) || 1)),
                  )
                }
              />
            </label>
          )}
          {preview && <DocumentResult result={preview} />}
          {typeof preview?.next_start === 'number' && (
            <Button variant="outline" disabled={busy} onClick={() => void load(preview.next_start as number)}>
              继续预览后续内容
            </Button>
          )}
        </div>
      )}
    </article>
  );
}

export function ArtifactCard({ task }: { task: FileTask }) {
  const artifact = task.context?.artifact as { name: string; path: string; workspace_id: string } | undefined;
  const [preview, setPreview] = useState<string | null>(null),
    [notice, setNotice] = useState('');
  const [location, setLocation] = useState(''),
    [busy, setBusy] = useState(false);
  if (!artifact || task.status !== 'complete') return null;
  async function load() {
    if (preview !== null) {
      setPreview(null);
      return;
    }
    setBusy(true);
    setNotice('');
    try {
      const response = await fetch(`/api/work/artifacts/${task.id}`);
      if (!response.ok) throw new Error('成果文件暂不可读取，可能已被移动、修改或撤销授权；请查看保存位置。');
      setPreview(await response.text());
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
    <article className="file-card" aria-label="总结成品">
      <strong>{artifact.name}</strong>
      <p>根据本任务已读取的资料整理，包含来源和阅读范围；单独保存为新文件。</p>
      <div className="work-actions">
        <Button variant="outline" disabled={busy} onClick={() => void load()}>
          {preview === null ? '预览总结文件' : '收起总结预览'}
        </Button>
        <a className="text-link" href={`/api/work/artifacts/${task.id}`} download>
          下载总结
        </a>
        <Button variant="ghost" onClick={() => void showLocation()}>
          查看保存位置
        </Button>
      </div>
      {location && <p className="file-location">{location}</p>}
      {notice && <p role="status">{notice}</p>}
      {preview !== null && <DocumentMarkdown text={preview} />}
    </article>
  );
}

export function ContinueTask({ task, onChanged }: { task: FileTask; onChanged: () => Promise<void> }) {
  const [busy, setBusy] = useState(false),
    [notice, setNotice] = useState('');
  if (!['waiting_limit', 'waiting_output'].includes(task.status)) return null;
  const pause = task.context?.pause as { reason?: string } | undefined;
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
      {task.status === 'waiting_output' && <p>在成果目录设置中选好已有文件夹后，点击保存；无需重新总结。</p>}
      <div className="work-actions">
        <Button disabled={busy} onClick={() => void decide(true)}>
          {task.status === 'waiting_output' ? '保存总结文件' : '继续下一轮处理'}
        </Button>
        <Button variant="outline" disabled={busy} onClick={() => void decide(false)}>
          取消任务并保留记录
        </Button>
      </div>
      {notice && <p role="status">{notice}</p>}
    </div>
  );
}

function ChatTaskCard({
  task,
  onChanged,
  onSettings,
  attachments,
}: {
  task: FileTask;
  onChanged: () => Promise<void>;
  onSettings: () => void;
  attachments: Attachment[];
}) {
  const [busy, setBusy] = useState(false),
    [notice, setNotice] = useState('');
  const summary = task.steps.find((step) => step.action === 'summarize')?.result;
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
    <article className="chat-task-card" aria-label={`文件任务：${task.title}`}>
      <div className="file-card-heading">
        <strong>{task.title}</strong>
        <span role="status">{taskStatuses[task.status]}</span>
      </div>
      {task.error && <p role="status">{task.error}</p>}
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
      <ArtifactCard task={task} />
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
      {notice && <p role="status">{notice}</p>}
    </article>
  );
}

export function ChatFileTasks({
  conversationId,
  onSettings,
  onWork,
  attachments = [],
}: {
  conversationId: string | null;
  onSettings: () => void;
  onWork: () => void;
  attachments?: Attachment[];
}) {
  const [tasks, setTasks] = useState<FileTask[]>([]),
    [notice, setNotice] = useState('');
  const refresh = useCallback(
    async (signal?: AbortSignal) => {
      if (!conversationId) return;
      const result = await request<FileTask[]>(
        `/work/tasks?conversation_id=${encodeURIComponent(conversationId)}&compact=true`,
        { signal },
      );
      if (!signal?.aborted) {
        setTasks(result);
        setNotice('');
      }
    },
    [conversationId],
  );
  useEffect(() => {
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
    <section className="chat-file-tasks" aria-label="聊天文件任务">
      <details open={tasks.some((task) => task.status === 'waiting_output')}>
        <summary>文件任务与成果目录</summary>
        <OutputFolder />
        <Button variant="ghost" onClick={onWork}>
          到工作台查看完整记录与恢复
        </Button>
      </details>
      {notice && <p role="status">{notice}</p>}
      {tasks.slice(0, 8).map((task) => (
        <ChatTaskCard
          key={task.id}
          task={task}
          onChanged={refresh}
          onSettings={onSettings}
          attachments={attachments}
        />
      ))}
      {tasks.length > 8 && (
        <Button variant="ghost" onClick={onWork}>
          查看更早的文件任务
        </Button>
      )}
    </section>
  );
}
