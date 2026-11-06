import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { request } from './api';
import type { components } from './generated/api-schema';
import './qq.css';

type Connection = Required<components['schemas']['Connection']>;
type Policy = Required<components['schemas']['Policy']>;
type Vision = { id: string; model: string; service: string; signature: string };
export type State = {
  deployment_mode?: 'desktop' | 'server';
  local_knowledge?: boolean;
  chat_view_ready?: boolean;
  sticker_controls_ready?: boolean;
  manual_profiles_ready?: boolean;
  connection: Connection;
  status: string;
  error: string;
  has_token: boolean;
  owner: string;
  last_event: number | null;
  policies: {
    kind: string;
    target: string;
    next_due: number | null;
    policy: Policy;
    skipped?: number;
    last_summary?: { state: string; error: string; end: number } | null;
  }[];
  vision_profiles: Vision[];
};
export type Peer = { kind: 'group' | 'private'; target: string; name: string; policy: Policy };
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
const localTime = (value: number) => new Date(value + 8 * 3600000).toISOString().slice(0, 16);
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

export function PolicyEditor({
  peer,
  state,
  busy,
  act,
  onSaved,
  onDirty,
  mode = 'chat',
}: {
  peer: Peer;
  state: State;
  busy: boolean;
  act: <T>(action: () => Promise<T>, success?: string) => Promise<T | undefined>;
  onSaved: (policy: Policy) => void;
  onDirty: (dirty: boolean) => void;
  mode?: 'chat' | 'summary';
}) {
  const active = useRef(true);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  const [policy, setPolicy] = useState(peer.policy);
  const [start, setStart] = useState(localTime(Date.now() - 86400000)),
    [end, setEnd] = useState(localTime(Date.now()));
  const [records, setRecords] = useState<
    { id: string; name: string; text: string; state: string; error: string }[] | null
  >(null);
  function edit(value: Policy | ((previous: Policy) => Policy)) {
    setPolicy(value);
    onDirty(true);
  }
  const set = <K extends keyof Policy>(key: K, value: Policy[K]) =>
    edit((previous) => ({ ...previous, [key]: value }));
  const rule = state.policies.find((item) => item.kind === peer.kind && item.target === peer.target);
  const [delivery, setDelivery] = useState<'panel' | 'owner' | 'group'>('panel');
  const destinations = (
    <>
      <option value="panel">仅保存面板</option>
      <option value="owner" disabled={!state.owner}>
        私发给主人
      </option>
      <option value="group" disabled={!policy.allow_group_send}>
        发回原群（须允许）
      </option>
    </>
  );
  return (
    <section className="qq-card">
      <h3>{mode === 'summary' ? '摘要设置' : '聊天设置'}</h3>
      {mode === 'summary' && !policy.collect && <p>此群尚未开启采集，请先到聊天管理 → 设置中开启。</p>}
      {mode === 'chat' && (
        <>
          <Toggle
            label="采集此范围的消息"
            value={policy.collect}
            onChange={(value) =>
              edit((previous) => ({
                ...previous,
                collect: value,
                ...(value ? {} : { chat: 'off', schedule: 'off' }),
              }))
            }
          />
          <Field label="聊天模式">
            <select
              value={policy.chat}
              onChange={(e) => set('chat', e.target.value as Policy['chat'])}
              disabled={!policy.collect}
            >
              <option value="off">关闭聊天</option>
              <option value="mention">
                {peer.kind === 'group' ? '仅被 @ 或 /瞬光 指令时回复' : '允许私聊回复'}
              </option>
              {peer.kind === 'group' && <option value="natural">适度自然参与</option>}
            </select>
          </Field>
          <p>
            采集、聊天、定时摘要与摘要投递分别控制。自然参与每群至少间隔 2 分钟、每小时最多 10
            次，消息过期或限流时仅采集。
          </p>
          {state.local_knowledge !== false ? (
            <Toggle
              label="允许使用角色知识库"
              value={policy.knowledge}
              onChange={(value) => set('knowledge', value)}
            />
          ) : (
            <p>轻量模式使用角色提示词，不启用本地知识库；聊天记忆继续保留。</p>
          )}
          <Toggle
            label="回复附带表情包"
            value={policy.stickers ?? true}
            onChange={(value) => set('stickers', value)}
          />
          <Field label="视觉模型与服务">
            <select
              value={policy.vision_profile + '|' + policy.vision_signature}
              onChange={(e) => {
                const [profile, signature] = e.target.value.split('|');
                edit((previous) => ({
                  ...previous,
                  vision_profile: profile,
                  vision_signature: signature ?? '',
                  images: false,
                }));
              }}
            >
              <option value="|">未选择</option>
              {state.vision_profiles.map((item) => (
                <option key={item.id} value={`${item.id}|${item.signature}`}>
                  {item.model} · {item.service}
                </option>
              ))}
            </select>
          </Field>
          <Toggle
            label="授权此范围按需识别图片（可能产生模型费用）"
            value={policy.images}
            onChange={(value) => set('images', value)}
          />
          <p>
            仅在回复或总结需要时识别，复用同一授权下的结果。视觉配置变化须重新授权；语音暂不解析，动态图仅首帧。
          </p>
        </>
      )}
      {mode === 'summary' && peer.kind === 'group' && (
        <>
          <hr />
          <h3>摘要与后台计划</h3>
          <Toggle
            label="单独允许摘要发回此群"
            value={policy.allow_group_send}
            onChange={(value) =>
              edit((previous) => ({
                ...previous,
                allow_group_send: value,
                delivery: !value && previous.delivery === 'group' ? 'panel' : previous.delivery,
              }))
            }
          />
          <div className="qq-grid">
            <Field label="定时总结">
              <select
                value={policy.schedule}
                disabled={!policy.collect}
                onChange={(e) => set('schedule', e.target.value as Policy['schedule'])}
              >
                <option value="off">关闭定时总结</option>
                <option value="daily">每天固定时间</option>
                <option value="interval">每隔若干小时</option>
              </select>
            </Field>
            {policy.schedule === 'daily' && (
              <Field label="每天执行时间（北京时间）">
                <Input
                  type="time"
                  value={policy.daily_time}
                  onChange={(e) => set('daily_time', e.target.value)}
                />
              </Field>
            )}
            {policy.schedule === 'interval' && (
              <Field label="间隔小时数">
                <Input
                  type="number"
                  min={1}
                  max={168}
                  value={policy.interval_hours}
                  onChange={(e) => set('interval_hours', Number(e.target.value))}
                />
              </Field>
            )}
            <Field label="总结窗口">
              <select
                value={policy.window}
                onChange={(e) => set('window', e.target.value as Policy['window'])}
              >
                <option value="incremental">自上次窗口结束以来</option>
                <option value="fixed">每日固定时段</option>
              </select>
            </Field>
            {policy.window === 'fixed' && (
              <>
                <Field label="时段开始（北京时间）">
                  <Input
                    type="time"
                    value={policy.window_start}
                    onChange={(e) => set('window_start', e.target.value)}
                  />
                </Field>
                <Field label="时段结束（北京时间）">
                  <Input
                    type="time"
                    value={policy.window_end}
                    onChange={(e) => set('window_end', e.target.value)}
                  />
                </Field>
              </>
            )}
            <Field label="定时摘要去向">
              <select
                value={policy.delivery}
                onChange={(e) => set('delivery', e.target.value as Policy['delivery'])}
              >
                {destinations}
              </select>
            </Field>
          </div>
          <p>
            下次执行：{showTime(rule?.next_due ?? null)}
            。首次启用先保存计划；无新消息不调用摘要模型、不投递。重启最多补做最近一个计划，不连续补发历史通知。
          </p>
          {rule?.last_summary && (
            <p>
              上次窗口结束：{showTime(rule.last_summary.end)} ·{' '}
              {statusLabels[rule.last_summary.state] ?? rule.last_summary.state}
              {rule.last_summary.error && ` · ${rule.last_summary.error}`}
            </p>
          )}
          {!!rule?.skipped && (
            <p>最近恢复时跳过 {rule.skipped} 个触发点，只补做最近一个计划；更早缺口可手动选择时间段。</p>
          )}
        </>
      )}
      <Button
        disabled={busy}
        onClick={() =>
          void act(async () => {
            const next = await request<Policy>(
              `/qq/policies/${peer.kind}/${peer.target}`,
              body('PUT', policy),
            );
            if (!active.current) return;
            setPolicy(next);
            onSaved(next);
            onDirty(false);
          }, '该范围权限已保存')
        }
      >
        保存此范围设置
      </Button>
      {mode === 'summary' && peer.kind === 'group' && (
        <>
          <hr />
          <h3>手动总结已采集消息</h3>
          <div className="qq-grid">
            <Field label="开始时间（北京时间）">
              <Input type="datetime-local" value={start} onChange={(e) => setStart(e.target.value)} />
            </Field>
            <Field label="结束时间（北京时间，不含）">
              <Input type="datetime-local" value={end} onChange={(e) => setEnd(e.target.value)} />
            </Field>
            <Field label="本次摘要去向">
              <select value={delivery} onChange={(e) => setDelivery(e.target.value as typeof delivery)}>
                {destinations}
              </select>
            </Field>
          </div>
          <Button
            disabled={busy || !policy.collect}
            onClick={() =>
              void act(
                () =>
                  request(
                    `/qq/summaries/${peer.target}`,
                    body('POST', {
                      start: Date.parse(start + '+08:00') / 1000,
                      end: Date.parse(end + '+08:00') / 1000,
                      delivery,
                    }),
                  ),
                '摘要任务已排队，请查看下方摘要历史',
              )
            }
          >
            生成这段时间的摘要
          </Button>
          <p>只读取开启采集后保存的消息，不自动拉取全部旧聊天。每次最多 32 天；超大窗口须缩短后重试。</p>
        </>
      )}
      {mode === 'chat' && (
        <details>
          <summary>采集记录与清理</summary>
          <div className="qq-actions">
            <Button
              variant="outline"
              disabled={busy}
              onClick={() =>
                void act(
                  async () => setRecords(await request(`/qq/records/${peer.kind}/${peer.target}`)),
                  '已读取最近采集记录',
                )
              }
            >
              查看采集记录
            </Button>
            <Button
              variant="outline"
              disabled={busy || policy.collect}
              onClick={() =>
                void act(async () => {
                  if (!window.confirm('清除此范围的采集消息与图片？手动资料保留。')) return;
                  await request(`/qq/records/${peer.kind}/${peer.target}`, body('DELETE'));
                  setRecords([]);
                }, '采集原文与图片已清理；手动资料保留，自动记忆在资料与记忆中管理')
              }
            >
              清理此范围采集记录
            </Button>
          </div>
          {records?.map((item) => (
            <p className="qq-message" key={item.id}>
              <strong>{item.name}：</strong>
              {item.text}
              <small>
                {' '}
                · {item.state} {item.error}
              </small>
            </p>
          ))}
        </details>
      )}
    </section>
  );
}
