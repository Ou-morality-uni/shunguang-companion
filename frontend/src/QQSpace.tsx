import { useEffect, useState, type ReactNode } from 'react';
import { MessageSquare } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { request, type ConnectionOptions } from './api';
import './qq.css';
import { QQManager } from './QQManager';
import type { Peer, State } from './QQPolicy';

type Connection = State['connection'];
type Summary = {
  id: string;
  target: string;
  start: number;
  end: number;
  state: string;
  content: string;
  error: string;
  delivery: string;
  sent: string;
};
const statusLabels: Record<string, string> = {
  connected: '已连接',
  connecting: '连接中',
  disconnected: '已断开，等待重连',
  disabled: '未启用',
  queued: '等待处理',
  generating: '正在整理',
  complete: '已完成',
  failed: '失败，可重试',
  empty: '无已采集消息',
  cancelled: '已取消',
  pending: '待投递',
  sending: '正在发送',
  sent: '已发送',
  uncertain: '发送结果待确认',
  revoked: '许可已撤销',
  not_required: '仅面板保存',
};
const showTime = (value: number | null) =>
  value ? new Date(value * 1000).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false }) : '—';
const body = (method: string, value?: unknown) => ({
  method,
  ...(value === undefined ? {} : { body: JSON.stringify(value) }),
});
function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="qq-field">
      <span>{label}</span>
      {children}
    </label>
  );
}
function Toggle({
  label,
  value,
  onChange,
}: {
  label: string;
  value: boolean;
  onChange: (value: boolean) => void;
}) {
  return (
    <label className="qq-toggle">
      <input type="checkbox" checked={value} onChange={(e) => onChange(e.target.checked)} />
      {label}
    </label>
  );
}

export function QQSpace() {
  const [state, setState] = useState<State | null>(null);
  const [connection, setConnection] = useState<Connection | null>(null);
  function editConnection(value: Connection) {
    setConnection(value);
    setDirty(true);
  }
  const [models, setModels] = useState<ConnectionOptions[]>([]);
  const [tab, setTab] = useState('connection');
  const [loadError, setLoadError] = useState('');
  const [error, setError] = useState(''),
    [notice, setNotice] = useState(''),
    [busy, setBusy] = useState(false);
  const [binding, setBinding] = useState<{ code: string; expires: number } | null>(null);
  const [summaries, setSummaries] = useState<Summary[]>([]);
  const [selected, setSelected] = useState<Peer | null>(null);
  const [dirty, setDirty] = useState(false);
  useEffect(() => {
    if (!dirty) return;
    const guard = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = '';
    };
    window.addEventListener('beforeunload', guard);
    return () => window.removeEventListener('beforeunload', guard);
  }, [dirty]);
  useEffect(() => {
    const abort = new AbortController();
    async function load(initial = false) {
      try {
        const next = await request<State>('/qq/state', { signal: abort.signal });
        if (abort.signal.aborted) return;
        setState(next);
        setLoadError('');
        if (initial) setConnection({ ...next.connection, token: '' });
        const records = await request<Summary[]>('/qq/summaries', { signal: abort.signal });
        if (!abort.signal.aborted) {
          setSummaries(records);
        }
      } catch (failure) {
        if (!abort.signal.aborted) setLoadError((failure as Error).message);
      }
    }
    void load(true);
    void request<ConnectionOptions[]>('/model-options', { signal: abort.signal })
      .then(setModels)
      .catch(() => {});
    const timer = window.setInterval(() => {
      if (!document.hidden) void load();
    }, 5000);
    return () => {
      abort.abort();
      window.clearInterval(timer);
    };
  }, []);
  async function act<T>(action: () => Promise<T>, success = '已保存') {
    setBusy(true);
    setError('');
    setNotice('');
    try {
      const result = await action();
      setNotice(success);
      return result;
    } catch (failure) {
      setError((failure as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-page qq-space">
      <header className="page-heading">
        <small>
          <MessageSquare size={15} /> QQ · 聊天管理
        </small>
        <h1>QQ 接入</h1>
        <p>
          {state?.deployment_mode === 'server'
            ? '人格沿用服务器角色设定。关闭电脑和浏览器后，服务器上的叶瞬光与 QQ 桥接继续运行。'
            : '人格与角色知识沿用现有设置。后台在关闭浏览器后继续运行；电脑需保持唤醒，叶瞬光后端与 QQ 桥接需保持启动。'}
        </p>
      </header>
      <div className="qq-status">
        <span className={state?.status === 'connected' ? 'qq-online' : ''}>●</span>
        {statusLabels[state?.status ?? ''] ?? '正在读取状态'}
        <span>主人：{state?.owner || '尚未绑定'}</span>
      </div>
      {state && (!state.chat_view_ready || !state.sticker_controls_ready || !state.manual_profiles_ready) && (
        <p role="alert" className="error-banner">
          后端尚未加载本轮 QQ 档案与聊天支持，请正常停止旧后端并重新启动叶瞬光；只刷新页面不会生效。
        </p>
      )}
      {(error || loadError || state?.error) && (
        <p role="alert" className="error-banner">
          {error || loadError || state?.error}
        </p>
      )}
      {notice && (
        <p role="status" className="qq-notice">
          {notice}
        </p>
      )}
      <div className="qq-tabs" aria-label="QQ 管理栏目">
        {Object.entries({
          connection: '连接',
          manager: '聊天管理',
          summaries: '群摘要',
        }).map(([key, label]) => (
          <Button
            key={key}
            variant={tab === key ? 'default' : 'ghost'}
            onClick={() => {
              if (dirty && !window.confirm('有未保存的修改，放弃并切换栏目？')) return;
              setDirty(false);
              setTab(key);
            }}
            aria-pressed={tab === key}
          >
            {label}
          </Button>
        ))}
      </div>
      {state && tab !== 'connection' && (
        <QQManager
          key={tab}
          mode={tab === 'summaries' ? 'summary' : 'chat'}
          state={state}
          selected={selected}
          onSelect={setSelected}
          dirty={dirty}
          onDirty={setDirty}
          busy={busy}
          act={act}
        />
      )}
      {tab === 'connection' && connection && (
        <section className="qq-card">
          <h2>连接独立 QQ 桥</h2>
          <p>
            NapCat 或兼容 OneBot v11 的 SnowLuma。使用正向 WebSocket、Universal 与 array
            消息格式；两端端口、路径及 Token 必须一致。
          </p>
          <div className="qq-grid">
            <Field label="机器人 QQ 号">
              <Input
                value={connection.bot_id}
                onChange={(e) => editConnection({ ...connection, bot_id: e.target.value })}
                inputMode="numeric"
              />
            </Field>
            <Field label="OneBot WebSocket 地址">
              <Input
                value={connection.url}
                onChange={(e) => editConnection({ ...connection, url: e.target.value })}
              />
            </Field>
            <Field label="OneBot Token">
              <Input
                type="password"
                autoComplete="new-password"
                value={connection.token}
                placeholder={state?.has_token ? '已加密保存；留空保留原值' : '填写桥接的独立 Token'}
                onChange={(e) => editConnection({ ...connection, token: e.target.value })}
              />
            </Field>
            <Field label="原始记录保留天数">
              <Input
                type="number"
                min={1}
                max={3650}
                value={connection.retention_days}
                onChange={(e) => editConnection({ ...connection, retention_days: Number(e.target.value) })}
              />
            </Field>
            <Field label="QQ 回复与摘要模型">
              <select
                value={
                  connection.model_choice
                    ? `${connection.model_choice.profile_id}|${connection.model_choice.model}`
                    : ''
                }
                onChange={(e) => {
                  const [profile, model] = e.target.value.split('|');
                  editConnection({
                    ...connection,
                    model_choice: profile ? { profile_id: profile, model, effort: 'default' } : null,
                  });
                }}
              >
                <option value="">沿用当前主模型</option>
                {models.flatMap((group) =>
                  group.configured
                    ? group.models.map((model) => (
                        <option key={`${group.id}|${model.id}`} value={`${group.id}|${model.id}`}>
                          {group.label} · {model.id}
                        </option>
                      ))
                    : [],
                )}
              </select>
            </Field>
          </div>
          <Toggle
            label="启用 QQ 连接"
            value={connection.enabled}
            onChange={(enabled) => editConnection({ ...connection, enabled })}
          />
          <Button
            disabled={busy}
            onClick={() =>
              void act(async () => {
                const next = await request<State>('/qq/connection', body('PATCH', connection));
                setState(next);
                setConnection({ ...next.connection, token: '' });
                setDirty(false);
              }, '配置已保存，后台将按开关连接')
            }
          >
            保存连接设置
          </Button>
          <p>
            {state?.deployment_mode === 'server'
              ? 'Token 使用服务器独立主密钥加密，不回显明文。'
              : 'Token 使用当前 Windows 账户加密，不回显明文。'}
            原始 QQ 消息与图片到期清理；摘要和独立长期记忆手动删除。主人共享对话遵循网页原有保留方式。
          </p>
          <hr />
          <h2>绑定我的 QQ</h2>
          <p>
            在面板生成 5 分钟有效的一次性码，再用你的 QQ
            私聊机器人发送指定文本。群内绑定无效。成功后仅该私聊与网页版共享私人记忆，并开启该私聊回复。
          </p>
          <div className="qq-actions">
            <Button
              disabled={busy}
              onClick={() =>
                void act(async () => setBinding(await request('/qq/binding', body('POST'))), '绑定码已生成')
              }
            >
              生成绑定码
            </Button>
            <Button
              variant="outline"
              disabled={busy || !state?.owner}
              onClick={() =>
                void act(async () => {
                  await request('/qq/binding', body('DELETE'));
                  setBinding(null);
                }, '已解绑并关闭旧私聊采集与回复')
              }
            >
              解绑
            </Button>
          </div>
          {binding && (
            <div className="qq-binding">
              <code>/绑定 {binding.code}</code>
              <p>有效至 {showTime(binding.expires)}；请仅在你的 QQ 私聊中发送。</p>
            </div>
          )}
        </section>
      )}
      {tab === 'summaries' && (
        <section className="qq-card">
          <h2>已保存摘要</h2>
          <p>
            每 5 秒刷新。默认只保存面板；原群投递须在群权限中单独允许。失败投递可重试；结果待确认时请先查看
            QQ，避免重复。
          </p>
          {!summaries.length && <p>还没有摘要。在上方选择群，设置定时任务或手动生成。</p>}
          {summaries
            .filter((item) => selected?.kind !== 'group' || item.target === selected.target)
            .map((item) => (
              <article className="qq-summary" key={item.id}>
                <h3>
                  群 {item.target} · {statusLabels[item.state] ?? item.state}
                </h3>
                <p>
                  {showTime(item.start)} 至 {showTime(item.end)} · 投递：
                  {statusLabels[item.sent] ?? item.sent}
                </p>
                {item.error && <p role="alert">{item.error}</p>}
                <pre>{item.content}</pre>
                <div className="qq-actions">
                  {item.state === 'failed' && (
                    <Button
                      disabled={busy}
                      onClick={() =>
                        void act(
                          () => request(`/qq/summaries/${item.id}/retry`, body('POST')),
                          '已排队重试生成',
                        )
                      }
                    >
                      重试生成
                    </Button>
                  )}
                  {item.state === 'complete' && item.sent === 'failed' && (
                    <Button
                      disabled={busy}
                      onClick={() =>
                        void act(
                          () => request(`/qq/summaries/${item.id}/deliver`, body('POST')),
                          '已尝试投递，请查看最新状态',
                        )
                      }
                    >
                      重试投递
                    </Button>
                  )}
                  <Button
                    variant="outline"
                    disabled={busy || item.state === 'generating' || item.sent === 'sending'}
                    onClick={() =>
                      void act(async () => {
                        await request(`/qq/summaries/${item.id}`, body('DELETE'));
                        setSummaries((items) => items.filter((v) => v.id !== item.id));
                      }, '摘要已删除')
                    }
                  >
                    删除摘要
                  </Button>
                </div>
              </article>
            ))}
        </section>
      )}
    </div>
  );
}
