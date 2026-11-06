import { useEffect, useRef, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { request } from './api';
import { QQChats } from './QQChats';
import { QQProfiles } from './QQProfiles';
import { PolicyEditor, type Peer, type State } from './QQPolicy';

export function QQManager({
  mode,
  state,
  selected,
  onSelect,
  dirty,
  onDirty,
  busy,
  act,
}: {
  mode: 'chat' | 'summary';
  state: State;
  selected: Peer | null;
  onSelect: (peer: Peer) => void;
  dirty: boolean;
  onDirty: (dirty: boolean) => void;
  busy: boolean;
  act: <T>(action: () => Promise<T>, success?: string) => Promise<T | undefined>;
}) {
  const [kind, setKind] = useState<'private' | 'group'>(
    mode === 'summary' ? 'group' : selected?.kind || 'private',
  );
  const [search, setSearch] = useState(''),
    [offset, setOffset] = useState(0),
    [revision, setRevision] = useState(0);
  const [page, setPage] = useState<{ items: Peer[]; total: number }>({ items: [], total: 0 });
  const [section, setSection] = useState<'messages' | 'profiles' | 'settings'>('messages');
  const [error, setError] = useState(''),
    [manual, setManual] = useState(''),
    [mobileDetail, setMobileDetail] = useState(Boolean(selected));
  const current = selected && (mode !== 'summary' || selected.kind === 'group') ? selected : null;
  const opening = useRef<AbortController | null>(null);
  useEffect(() => () => opening.current?.abort(), []);
  useEffect(() => {
    const abort = new AbortController();
    void request<typeof page>(`/qq/peers/${kind}?search=${encodeURIComponent(search)}&offset=${offset}`, {
      signal: abort.signal,
    })
      .then((value) => {
        if (!abort.signal.aborted) {
          setPage(value);
          setError('');
        }
      })
      .catch((e) => {
        if (!abort.signal.aborted) setError(e.message);
      });
    return () => abort.abort();
  }, [kind, search, offset, revision]);
  function navigate(action: () => void) {
    if (dirty && !window.confirm('有未保存的修改，放弃并切换？')) return;
    opening.current?.abort();
    onDirty(false);
    action();
  }
  function select(peer: Peer) {
    navigate(() => {
      onSelect(peer);
      setMobileDetail(true);
      setSection('messages');
    });
  }
  return (
    <div className={`qq-manager ${mobileDetail && current ? 'qq-show-detail' : ''}`}>
      <aside className="qq-card qq-manager-list" aria-label="聊天列表">
        <div className="qq-actions">
          {mode === 'chat' ? (
            (['private', 'group'] as const).map((value) => (
              <Button
                key={value}
                variant={kind === value ? 'default' : 'ghost'}
                onClick={() => {
                  opening.current?.abort();
                  setKind(value);
                  setSearch('');
                  setOffset(0);
                }}
              >
                {value === 'group' ? '群聊' : '私聊'}
              </Button>
            ))
          ) : (
            <h2>选择群聊</h2>
          )}
          <Button
            variant="ghost"
            disabled={busy}
            onClick={() =>
              void act(async () => {
                await request('/qq/refresh', { method: 'POST' });
                setRevision((v) => v + 1);
              }, '好友与群列表已刷新')
            }
          >
            刷新列表
          </Button>
        </div>
        <label className="qq-field">
          <span>搜索名称或 QQ 号</span>
          <Input
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setOffset(0);
            }}
          />
        </label>
        {error && <p role="alert">{error}</p>}
        <div className="qq-peer-list">
          {page.items.map((item) => (
            <button
              type="button"
              key={item.target}
              aria-pressed={current?.kind === item.kind && current.target === item.target}
              className={current?.kind === item.kind && current.target === item.target ? 'qq-selected' : ''}
              onClick={() => select(item)}
            >
              <strong>{item.name}</strong>
              <span>
                {item.target} · {item.policy.collect ? '采集已开' : '采集关闭'} ·{' '}
                {item.policy.chat === 'off'
                  ? '聊天关闭'
                  : item.policy.chat === 'natural'
                    ? '适度参与'
                    : '触发回复'}
              </span>
            </button>
          ))}
        </div>
        {!page.total && <p>暂无匹配聊天。刷新列表，或输入号码提前配置。</p>}
        <div className="qq-actions">
          <Button variant="ghost" disabled={!offset} onClick={() => setOffset((v) => Math.max(0, v - 30))}>
            上一页
          </Button>
          <span>{page.total} 项</span>
          <Button
            variant="ghost"
            disabled={offset + 30 >= page.total}
            onClick={() => setOffset((v) => v + 30)}
          >
            下一页
          </Button>
        </div>
        <details>
          <summary>按号码打开</summary>
          <form
            onSubmit={async (e) => {
              e.preventDefault();
              if (dirty && !window.confirm('有未保存的修改，放弃并打开？')) return;
              opening.current?.abort();
              const abort = new AbortController();
              opening.current = abort;
              try {
                const policy = await request<Peer['policy']>(`/qq/policies/${kind}/${manual}`, {
                  signal: abort.signal,
                });
                if (abort.signal.aborted) return;
                onDirty(false);
                onSelect({ kind, target: manual, name: manual, policy });
                setMobileDetail(true);
                setSection('profiles');
              } catch (e) {
                if (!abort.signal.aborted) setError((e as Error).message);
              }
            }}
          >
            <label className="qq-field">
              <span>{kind === 'group' ? '群号' : '联系人 QQ 号'}</span>
              <Input
                required
                pattern="[0-9]{5,20}"
                inputMode="numeric"
                value={manual}
                onChange={(e) => setManual(e.target.value)}
              />
            </label>
            <Button type="submit" variant="outline">
              打开配置
            </Button>
          </form>
        </details>
      </aside>
      <div className="qq-manager-detail">
        {!current ? (
          <section className="qq-card">
            <h2>{mode === 'summary' ? '为群聊安排摘要' : '管理 QQ 聊天'}</h2>
            <p>
              从左侧选择{mode === 'summary' ? '群聊' : '联系人或群聊'}
              ；手机请在列表中点开。保存档案不会自动开启采集或回复。
            </p>
          </section>
        ) : (
          <>
            <div className="qq-detail-heading">
              <Button
                className="qq-mobile-back"
                variant="ghost"
                onClick={() => navigate(() => setMobileDetail(false))}
              >
                返回聊天列表
              </Button>
              <h2>
                {current.name}{' '}
                <small>
                  {current.target} · {current.kind === 'group' ? '群聊' : '私聊'}
                </small>
              </h2>
              <p>
                {current.policy.collect ? '采集已开' : '采集关闭'} ·{' '}
                {current.policy.chat === 'off'
                  ? '聊天关闭'
                  : current.policy.chat === 'natural'
                    ? '适度参与'
                    : '触发回复'}{' '}
                · 表情{current.policy.stickers === false ? '关闭' : '开启'}
              </p>
            </div>
            {mode === 'chat' && (
              <div className="qq-tabs" aria-label="聊天详情栏目">
                {(
                  [
                    ['messages', '消息'],
                    ['profiles', '资料与记忆'],
                    ['settings', '设置'],
                  ] as const
                ).map(([value, label]) => (
                  <Button
                    key={value}
                    variant={section === value ? 'default' : 'ghost'}
                    aria-pressed={section === value}
                    onClick={() => navigate(() => setSection(value))}
                  >
                    {label}
                  </Button>
                ))}
              </div>
            )}
            {mode === 'chat' && section === 'messages' && (
              <QQChats key={`${current.kind}/${current.target}`} chat={{ ...current, count: 0, stamp: 0 }} />
            )}
            {mode === 'chat' && section === 'profiles' && (
              <section className="qq-card">
                <QQProfiles
                  key={`${current.kind}/${current.target}`}
                  kind={current.kind}
                  target={current.target}
                  name={current.name}
                  onDirty={onDirty}
                />
              </section>
            )}
            {(mode === 'summary' || section === 'settings') && (
              <PolicyEditor
                key={`${current.kind}/${current.target}/${mode}`}
                mode={mode}
                peer={current}
                state={state}
                busy={busy}
                act={act}
                onDirty={onDirty}
                onSaved={(policy) => {
                  onSelect({ ...current, policy });
                  setRevision((v) => v + 1);
                }}
              />
            )}
          </>
        )}
      </div>
    </div>
  );
}
