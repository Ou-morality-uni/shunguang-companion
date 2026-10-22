import { useEffect, useRef, useState } from 'react';
import { FolderOpen, Plus, RefreshCw, RotateCcw, Square, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { request, type FileTask, type FileTaskInput, type Workspace } from './api';

type Step = FileTaskInput['steps'][number];
const actions: Record<Step['action'], string> = {
  list: '列出目录',
  read: '读取文本',
  write: '创建／修改文本',
  move: '移动／改名',
  delete: '申请删除',
};
const statuses: Record<FileTask['status'], string> = {
  queued: '排队中',
  running: '执行中',
  waiting_approval: '等待删除授权',
  complete: '已完成',
  failed: '已停止：发生错误',
  cancelled: '已取消',
  interrupted: '服务重启后中断',
  restoring: '恢复中',
  restored: '已恢复',
};
const active = new Set(['queued', 'running', 'restoring']);

export function WorkSpace() {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [tasks, setTasks] = useState<FileTask[]>([]);
  const [folder, setFolder] = useState('');
  const [chosen, setChosen] = useState('');
  const [title, setTitle] = useState('文件任务');
  const [steps, setSteps] = useState<Step[]>([{ action: 'list', path: '.' }]);
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const sequence = useRef(0);

  async function refresh(signal?: AbortSignal) {
    const version = ++sequence.current;
    const [folders, records] = await Promise.all([
      request<Workspace[]>('/work/workspaces', { signal }),
      request<FileTask[]>('/work/tasks', { signal }),
    ]);
    if (version !== sequence.current || signal?.aborted) return;
    setWorkspaces(folders);
    setTasks(records);
  }
  useEffect(() => {
    const controller = new AbortController();
    let polling = false;
    const poll = async () => {
      if (polling) return;
      polling = true;
      try {
        await refresh(controller.signal);
      } catch (error) {
        if (!controller.signal.aborted) setNotice((error as Error).message);
      } finally {
        polling = false;
      }
    };
    void poll();
    const timer = window.setInterval(() => {
      if (!document.hidden) void poll();
    }, 3000);
    return () => {
      controller.abort();
      clearInterval(timer);
    };
  }, []);

  async function perform(action: () => Promise<unknown>, message: string) {
    setBusy(true);
    setNotice('');
    try {
      await action();
      await refresh();
      setNotice(message);
    } catch (error) {
      setNotice((error as Error).message);
    } finally {
      setBusy(false);
    }
  }
  function update(index: number, value: Step) {
    setSteps((items) => items.map((item, position) => (position === index ? value : item)));
  }
  const selected = workspaces.find((item) => item.id === chosen && item.enabled);
  const post = (path: string, body?: unknown) =>
    request(path, {
      method: 'POST',
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });

  return (
    <div className="space-page workbench">
      <div className="page-heading">
        <span className="eyebrow">LET’S WORK TOGETHER</span>
        <h1>手边的事，一起理顺。</h1>
        <p>先授权本机工作文件夹。你可以在这里安排文件操作，也可以回到对话中交给瞬光。</p>
      </div>
      {notice && (
        <div className="settings-notice" role="status">
          {notice}
        </div>
      )}
      <section className="work-card glass" aria-label="工作文件夹授权">
        <h3>
          <FolderOpen size={18} /> 工作文件夹
        </h3>
        <p className="space-note">
          授权后，可自动读取、创建、修改和移动范围内的文件；修改前备份，删除另行确认。授权仅在本机使用。
        </p>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            void perform(async () => {
              const workspace = await request<Workspace>('/work/workspaces', {
                method: 'POST',
                body: JSON.stringify({ path: folder }),
              });
              setChosen(workspace.id);
              setFolder('');
            }, '工作文件夹已授权。');
          }}
        >
          <label className="field">
            本机文件夹完整路径
            <Input
              value={folder}
              onChange={(event) => setFolder(event.target.value)}
              placeholder="例如 D:\我的工作资料"
              required
              maxLength={1000}
            />
          </label>
          <Button disabled={busy || !folder.trim()} type="submit">
            授权此文件夹
          </Button>
        </form>
        <ul className="work-folders">
          {workspaces.map((workspace) => (
            <li key={workspace.id}>
              <span>
                {workspace.path}
                <small>{workspace.enabled ? '已授权' : '已撤销'}</small>
              </span>
              {workspace.enabled && (
                <Button
                  variant="outline"
                  disabled={busy}
                  onClick={() =>
                    void perform(
                      () => request(`/work/workspaces/${workspace.id}`, { method: 'DELETE' }),
                      '已撤销授权，相关任务停止；原文件和恢复记录保留。恢复前需要重新授权此文件夹。',
                    )
                  }
                >
                  撤销授权
                </Button>
              )}
            </li>
          ))}
        </ul>
      </section>
      <section className="work-card glass" aria-label="安排文件任务">
        <h3>安排文件任务</h3>
        <p className="space-note">
          本版支持已有目录内的普通文件操作和 UTF-8 文本。单文件最多 20 MiB，单任务最多 50
          步；办公文档阅读及命令执行按后续版本接入。
        </p>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            void perform(
              () => post('/work/tasks', { workspace_id: chosen, title, steps }),
              '任务已提交，请查看下方记录；包含删除时须先授权。',
            );
          }}
        >
          <label className="field">
            工作文件夹
            <select value={chosen} onChange={(event) => setChosen(event.target.value)} required>
              <option value="">请选择已授权文件夹</option>
              {workspaces
                .filter((item) => item.enabled)
                .map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.path}
                  </option>
                ))}
            </select>
          </label>
          <label className="field">
            任务名称
            <Input
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              required
              maxLength={120}
            />
          </label>
          {steps.map((step, index) => (
            <div className="work-step" key={index}>
              <label className="field">
                操作 {index + 1}
                <select
                  value={step.action}
                  onChange={(event) => {
                    const action = event.target.value as Step['action'];
                    update(index, {
                      action,
                      path: action === 'list' ? '.' : '',
                      ...(action === 'write' ? { content: '' } : {}),
                      ...(action === 'move' ? { destination: '' } : {}),
                    });
                  }}
                >
                  {Object.entries(actions).map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field">
                相对路径 {index + 1}
                <Input
                  value={step.path ?? '.'}
                  onChange={(event) => update(index, { ...step, path: event.target.value })}
                  required
                  maxLength={500}
                  placeholder="例如 资料/说明.txt；列根目录填 ."
                />
              </label>
              {step.action === 'move' && (
                <label className="field">
                  目标相对路径 {index + 1}
                  <Input
                    value={step.destination ?? ''}
                    onChange={(event) => update(index, { ...step, destination: event.target.value })}
                    required
                    maxLength={500}
                  />
                </label>
              )}
              {step.action === 'write' && (
                <label className="field">
                  完整文本内容 {index + 1}
                  <textarea
                    value={step.content ?? ''}
                    onChange={(event) => update(index, { ...step, content: event.target.value })}
                    rows={5}
                    maxLength={200000}
                  />
                  <small>已有文件会以这里的完整内容替换，并提前备份。</small>
                </label>
              )}
              {steps.length > 1 && (
                <Button
                  variant="ghost"
                  type="button"
                  aria-label={`移除操作 ${index + 1}`}
                  onClick={() => setSteps((items) => items.filter((_, position) => position !== index))}
                >
                  <X size={15} />
                  移除此步
                </Button>
              )}
            </div>
          ))}
          <div className="work-actions">
            <Button
              variant="outline"
              type="button"
              disabled={steps.length >= 50 || busy}
              onClick={() => setSteps((items) => [...items, { action: 'list', path: '.' }])}
            >
              <Plus size={15} />
              添加一步
            </Button>
            <Button type="submit" disabled={busy || !selected}>
              提交任务
            </Button>
          </div>
        </form>
      </section>
      <section aria-label="文件任务记录">
        <div className="work-actions">
          <h3>最近任务</h3>
          <Button
            variant="ghost"
            disabled={busy}
            onClick={() => void perform(() => refresh(), '任务记录已刷新。')}
          >
            <RefreshCw size={15} />
            刷新
          </Button>
        </div>
        {!tasks.length && <p className="space-note">还没有文件任务。授权后，从列出目录开始试试吧。</p>}
        {tasks.map((task) => (
          <article className="work-card glass" key={task.id} aria-label={`任务：${task.title}`}>
            <div className="work-actions">
              <h3>{task.title}</h3>
              <span>{statuses[task.status]}</span>
            </div>
            <p className="space-note">
              {workspaces.find((item) => item.id === task.workspace_id)?.path ?? '工作文件夹'} ·{' '}
              {new Date(task.created_at).toLocaleString()}
            </p>
            {task.error && <p role="status">{task.error}</p>}
            <ol className="work-results">
              {task.steps.map((step, index) => (
                <li key={index}>
                  <span>
                    {actions[step.action]}：{step.path}
                    {step.destination ? ` → ${step.destination}` : ''}
                  </span>
                  <small>
                    {(
                      {
                        pending: '未执行',
                        prepared: '已备份／待核对',
                        applied: '已执行',
                        complete: '已完成',
                        restoring: '恢复中',
                        restored: '已恢复',
                      } as Record<string, string>
                    )[step.state] ?? step.state}
                  </small>
                  {step.result && (
                    <details>
                      <summary>查看结果</summary>
                      {typeof step.result.text === 'string' && <pre>{step.result.text}</pre>}
                      {Array.isArray(step.result.entries) && (
                        <ul>
                          {(step.result.entries as Array<{ name: string; directory: boolean }>).map(
                            (entry) => (
                              <li key={entry.name}>
                                {entry.directory ? '文件夹：' : '文件：'}
                                {entry.name}
                              </li>
                            ),
                          )}
                        </ul>
                      )}
                      {step.result.truncated === true && <p>内容较长，当前只显示前一部分。</p>}
                      {typeof step.result.message === 'string' && <p>{step.result.message}</p>}
                    </details>
                  )}
                </li>
              ))}
            </ol>
            {task.status === 'waiting_approval' && (
              <div className="work-approval" role="group" aria-label="删除授权">
                <p>
                  请核对以上工作文件夹和全部操作。本任务包含删除，尚未执行任何步骤；同意后按这份清单执行，文件变化时停止。
                </p>
                <div className="work-actions">
                  <Button
                    disabled={busy}
                    onClick={() =>
                      void perform(
                        () => post(`/work/tasks/${task.id}/approval`, { approved: true }),
                        '已授权此任务，执行结果以记录为准。',
                      )
                    }
                  >
                    同意执行此任务（含删除）
                  </Button>
                  <Button
                    variant="outline"
                    disabled={busy}
                    onClick={() =>
                      void perform(
                        () => post(`/work/tasks/${task.id}/approval`, { approved: false }),
                        '已拒绝，此任务未执行。',
                      )
                    }
                  >
                    拒绝
                  </Button>
                </div>
              </div>
            )}
            <div className="work-actions">
              {active.has(task.status) && (
                <Button
                  variant="outline"
                  disabled={busy}
                  onClick={() =>
                    void perform(
                      () => post(`/work/tasks/${task.id}/cancel`),
                      '已请求停止，将在当前文件操作结束后停止后续步骤。',
                    )
                  }
                >
                  <Square size={14} />
                  取消任务
                </Button>
              )}
              {task.can_restore && (
                <Button
                  variant="outline"
                  disabled={busy}
                  onClick={() =>
                    void perform(
                      () => post(`/work/tasks/${task.id}/restore`),
                      '正在核对并恢复本任务的修改；若文件被再次修改，将停止以免覆盖。',
                    )
                  }
                >
                  <RotateCcw size={15} />
                  恢复本次修改
                </Button>
              )}
            </div>
          </article>
        ))}
      </section>
    </div>
  );
}
