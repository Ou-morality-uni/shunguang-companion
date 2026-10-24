import { GlideSelect } from './components/ui/glide-select';
import { useEffect, useRef, useState } from 'react';
import { FolderOpen, Plus, RefreshCw, RotateCcw, Square, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { request, type FileTask, type FileTaskInput, type Workspace } from './api';
import { DocumentResult, UploadDocuments, VisionApproval } from './DocumentControls';
import { ArtifactCard, ContinueTask, OutputFolder, taskStatuses } from './FileTasks';
import { OfficeCapabilities } from './OfficeCapabilities';

type Step = FileTaskInput['steps'][number];
const actions: Record<string, string> = {
  list: '列出目录',
  read: '读取文本',
  write: '创建／修改文本',
  move: '移动／改名',
  delete: '申请删除',
  read_document: '阅读文档／代码／图片',
  upload: '上传副本',
  summarize: '整理总结',
};
const active = new Set(['queued', 'running', 'restoring']);

export function WorkSpace({ onModelSettings }: { onModelSettings?: () => void }) {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [tasks, setTasks] = useState<FileTask[]>([]);
  const [folder, setFolder] = useState('');
  const [chosen, setChosen] = useState('');
  const [title, setTitle] = useState('文件任务');
  const [steps, setSteps] = useState<Step[]>([{ action: 'list', path: '.' }]);
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [instruction, setInstruction] = useState('总结这些资料的主要内容，并标注来源位置。');
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
        <p>上传资料副本，或授权本机工作文件夹。你可以在这里安排阅读与总结，也可以回到对话中交给瞬光。</p>
      </div>
      {notice && (
        <div className="settings-notice" role="status">
          {notice}
        </div>
      )}
      <UploadDocuments
        onModelSettings={onModelSettings}
        onUploaded={(workspace, uploaded) => {
          setChosen(workspace.id);
          setSteps(uploaded);
          setTitle('阅读上传资料');
          void refresh();
        }}
      />
      <section className="work-card glass" aria-label="成果目录">
        <h3>成果保存位置</h3>
        <OutputFolder />
        <OfficeCapabilities />
      </section>
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
          支持六类资料阅读和基础文件操作。文档按所选范围提取，保留来源位置；未读、截断和未识别内容会注明。Office
          成品制作与命令执行按后续版本接入。
        </p>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            void perform(
              () =>
                post('/work/tasks', {
                  workspace_id: chosen,
                  title,
                  steps,
                  ...(steps.some((step) => step.action === 'read_document') ? { instruction } : {}),
                }),
              '任务已提交，请查看下方记录；包含删除或替代图像识别时会等待授权。',
            );
          }}
        >
          <label className="field">
            工作文件夹
            <GlideSelect
              label="工作文件夹"
              placeholder="请选择已授权文件夹"
              value={chosen}
              onValueChange={setChosen}
              required
              options={workspaces
                .filter((item) => item.enabled)
                .map((item) => ({ value: item.id, label: item.path }))}
            />
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
                <GlideSelect
                  label={`操作 ${index + 1}`}
                  value={step.action}
                  onValueChange={(value) => {
                    const action = value as Step['action'];
                    update(index, {
                      action,
                      path: action === 'list' ? '.' : '',
                      ...(action === 'write' ? { content: '' } : {}),
                      ...(action === 'move' ? { destination: '' } : {}),
                    });
                  }}
                  options={Object.entries(actions)
                    .filter(([value]) => !['upload', 'summarize'].includes(value))
                    .map(([value, label]) => ({ value, label }))}
                />
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
              {step.action === 'read_document' && (
                <>
                  <label className="field">
                    阅读方式 {index + 1}
                    <GlideSelect
                      label={`阅读方式 ${index + 1}`}
                      value={step.scope ?? 'range'}
                      onValueChange={(value) => update(index, { ...step, scope: value as Step['scope'] })}
                      options={[
                        { value: 'range', label: '仅读指定范围' },
                        { value: 'full', label: '整份分批阅读' },
                        { value: 'focused', label: '按关键词定位相关范围' },
                      ]}
                    />
                  </label>
                  {step.scope === 'focused' && (
                    <label className="field">
                      定位关键词 {index + 1}
                      <Input
                        value={step.query ?? ''}
                        maxLength={300}
                        onChange={(event) => update(index, { ...step, query: event.target.value })}
                        placeholder="用空格或逗号分隔；统计和排名请选择整份阅读"
                      />
                    </label>
                  )}
                  {(step.scope ?? 'range') === 'range' && (
                    <div className="field-row">
                      <label className="field">
                        起始位置 {index + 1}
                        <Input
                          type="number"
                          min={1}
                          max={1000000}
                          value={step.start ?? 1}
                          onChange={(event) => update(index, { ...step, start: Number(event.target.value) })}
                        />
                      </label>
                      <label className="field">
                        读取数量 {index + 1}
                        <Input
                          type="number"
                          min={1}
                          max={50}
                          value={step.limit ?? 20}
                          onChange={(event) => update(index, { ...step, limit: Number(event.target.value) })}
                        />
                      </label>
                    </div>
                  )}
                  <p className="space-note">
                    位置从 1 开始：PDF 按页，Word 按段落／表格块，Excel 按工作表，PPT
                    按幻灯片，代码按行；图片只处理第一帧。
                  </p>
                  <label className="field">
                    <span>
                      <input
                        type="checkbox"
                        checked={step.visual ?? false}
                        onChange={(event) => update(index, { ...step, visual: event.target.checked })}
                      />{' '}
                      PDF 页面视觉理解（含矢量图表）
                    </span>
                    <small>
                      扫描页和内嵌图片自动按能力处理；勾选后也会识别所选 PDF
                      页面整体，可能增加模型调用。每次最多 8 幅。
                    </small>
                  </label>
                </>
              )}
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
          {steps.some((step) => step.action === 'read_document') && (
            <label className="field">
              阅读要求（留空只提取，不调用模型总结）
              <textarea
                value={instruction}
                onChange={(event) => setInstruction(event.target.value)}
                maxLength={4000}
                rows={3}
              />
            </label>
          )}
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
              <span>{taskStatuses[task.status]}</span>
            </div>
            <p className="space-note">
              {workspaces.find((item) => item.id === task.workspace_id)?.path ?? '工作文件夹'} ·{' '}
              {new Date(task.created_at).toLocaleString()}
            </p>
            {task.error && <p role="status">{task.error}</p>}
            {!!task.events?.length && (
              <details>
                <summary>瞬光的工作提示记录</summary>
                <ul>
                  {task.events?.map((event) => (
                    <li key={String(event.seq)}>{String(event.text)}</li>
                  ))}
                </ul>
              </details>
            )}
            <ol className="work-results">
              {task.steps.map((step, index) => (
                <li key={index}>
                  <span>
                    {actions[step.action]}：{step.action === 'summarize' ? '本任务已读取的资料' : step.path}
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
                        waiting_vision: '等待图像识别授权',
                      } as Record<string, string>
                    )[step.state] ?? step.state}
                  </small>
                  {step.result && (
                    <details>
                      <summary>查看结果</summary>
                      {typeof step.result.text === 'string' && <pre>{step.result.text}</pre>}
                      <DocumentResult result={step.result} />
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
                  {step.vision_request && task.status === 'waiting_vision' && (
                    <VisionApproval
                      taskId={task.id}
                      info={step.vision_request}
                      onChanged={refresh}
                      onModelSettings={onModelSettings}
                    />
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
            <ContinueTask task={task} onChanged={refresh} />
            <ArtifactCard task={task} />
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
