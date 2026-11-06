import { useEffect, useRef, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { request } from './api';
import type { components } from './generated/api-schema';

type Kind = 'private' | 'group';
type Entry = { key: string; title?: string; value: string; visibility: 'group' | 'self' };
type Profile = { bot: string; revision: number; entries: Entry[] };
type MemberPage = components['schemas']['MemberPage'];
type Member = components['schemas']['Member'];
const person = [
  ['name', '称呼'],
  ['aliases', '别名'],
  ['identity', '身份／关系'],
  ['interests', '兴趣偏好'],
  ['communication', '交流偏好'],
  ['ongoing', '长期事项'],
];
const group = [
  ['purpose', '群用途'],
  ['background', '共同背景'],
  ['terms', '常用术语'],
  ['summary_focus', '摘要关注点'],
];

export function QQProfiles({
  kind,
  target,
  name,
  onDirty,
}: {
  kind: Kind;
  target: string;
  name: string;
  onDirty: (dirty: boolean) => void;
}) {
  const [view, setView] = useState<'group' | 'members'>('group');
  const [member, setMember] = useState<Member | null>(null);
  const [search, setSearch] = useState(''),
    [offset, setOffset] = useState(0),
    [revision, setRevision] = useState(0);
  const [page, setPage] = useState<MemberPage | null>(null),
    [error, setError] = useState(''),
    [manual, setManual] = useState('');
  const [dirty, setDirty] = useState(false);
  const refresh = useRef(false);
  function changeDirty(value: boolean) {
    setDirty(value);
    onDirty(value);
  }
  function leave(action: () => void) {
    if (dirty && !window.confirm('有未保存的资料，放弃修改并离开？')) return;
    changeDirty(false);
    action();
  }
  useEffect(() => {
    if (kind !== 'group') return;
    const abort = new AbortController();
    const force = refresh.current;
    refresh.current = false;
    void request<MemberPage>(
      `/qq/members/${target}?search=${encodeURIComponent(search)}&offset=${offset}${force ? '&refresh=true' : ''}`,
      {
        signal: abort.signal,
      },
    )
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
  }, [kind, target, search, offset, revision]);
  return (
    <div className="qq-profiles">
      {kind === 'group' && (
        <div className="qq-actions">
          <Button
            variant={view === 'group' ? 'default' : 'ghost'}
            onClick={() =>
              leave(() => {
                setView('group');
                setMember(null);
              })
            }
          >
            群资料
          </Button>
          <Button
            variant={view === 'members' ? 'default' : 'ghost'}
            onClick={() =>
              leave(() => {
                setView('members');
                setMember(null);
              })
            }
          >
            成员
          </Button>
        </div>
      )}
      {error && <p role="alert">{error}</p>}
      {kind === 'group' && view === 'members' && !member ? (
        <>
          <div className="qq-actions">
            <label className="qq-field qq-grow">
              <span>搜索成员昵称、群名片或 QQ 号</span>
              <Input
                value={search}
                onChange={(e) => {
                  setSearch(e.target.value);
                  setOffset(0);
                }}
              />
            </label>
            <Button
              variant="outline"
              onClick={() => {
                refresh.current = true;
                setRevision((v) => v + 1);
              }}
            >
              刷新成员
            </Button>
          </div>
          <p>{page?.notice || '按需读取本群成员…'}</p>
          <div className="qq-peer-list qq-member-list">
            {page?.items.map((item) => (
              <button type="button" key={item.user_id} onClick={() => setMember(item)}>
                <strong>{item.card || item.name}</strong>
                <span>
                  {item.name} · {item.user_id} ·{' '}
                  {{ bridge: '桥接名单', captured: '已采集', manual: '手动建档' }[item.source]}
                </span>
              </button>
            ))}
          </div>
          {page && !page.total && <p>尚无成员记录。可以输入 QQ 号提前建档。</p>}
          <div className="qq-actions">
            <Button variant="ghost" disabled={!offset} onClick={() => setOffset((v) => Math.max(0, v - 30))}>
              上一页
            </Button>
            <span>{page?.total ?? 0} 位成员</span>
            <Button
              variant="ghost"
              disabled={offset + 30 >= (page?.total ?? 0)}
              onClick={() => setOffset((v) => v + 30)}
            >
              下一页
            </Button>
          </div>
          <form
            className="qq-actions"
            onSubmit={(e) => {
              e.preventDefault();
              setMember({ user_id: manual, name: manual, card: '', source: 'manual' });
            }}
          >
            <label className="qq-field qq-grow">
              <span>手动添加成员 QQ 号</span>
              <Input
                required
                pattern="[0-9]{5,20}"
                inputMode="numeric"
                value={manual}
                onChange={(e) => setManual(e.target.value)}
              />
            </label>
            <Button type="submit" variant="outline">
              按 QQ 号建档
            </Button>
          </form>
        </>
      ) : (
        <>
          {member && (
            <div className="qq-actions">
              <Button
                variant="ghost"
                onClick={() =>
                  leave(() => {
                    setMember(null);
                    setRevision((v) => v + 1);
                  })
                }
              >
                返回成员列表
              </Button>
              <strong>
                {name} › {member.card || member.name} · {member.user_id}
              </strong>
            </div>
          )}
          <ProfileEditor
            key={`${kind}/${target}/${member?.user_id || ''}`}
            kind={kind}
            target={target}
            subject={member?.user_id || ''}
            onDirty={changeDirty}
          />
        </>
      )}
    </div>
  );
}

function ProfileEditor({
  kind,
  target,
  subject,
  onDirty,
}: {
  kind: Kind;
  target: string;
  subject: string;
  onDirty: (value: boolean) => void;
}) {
  const active = useRef(true);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  const [saved, setSaved] = useState<Profile | null>(null),
    [entries, setEntries] = useState<Entry[]>([]);
  const [error, setError] = useState(''),
    [notice, setNotice] = useState(''),
    [busy, setBusy] = useState(false),
    [dirty, setDirty] = useState(false),
    [reload, setReload] = useState(0);
  const base = kind === 'group' && !subject;
  const fields = base ? group : person;
  const path = `/qq/profiles/${kind}/${target}?subject=${subject}`;
  useEffect(() => {
    const abort = new AbortController();
    void request<Profile>(path, { signal: abort.signal })
      .then((value) => {
        if (!abort.signal.aborted) {
          setSaved(value);
          setEntries(value.entries);
          setError('');
        }
      })
      .catch((e) => {
        if (!abort.signal.aborted) setError(e.message);
      });
    return () => abort.abort();
  }, [path, reload]);
  useEffect(() => {
    if (!dirty) return;
    const guard = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = '';
    };
    window.addEventListener('beforeunload', guard);
    return () => window.removeEventListener('beforeunload', guard);
  }, [dirty]);
  function changed(next: Entry[]) {
    setEntries(next);
    setDirty(true);
    onDirty(true);
    setNotice('');
  }
  function update(key: string, patch: Partial<Entry>) {
    const current =
      entries.find((e) => e.key === key) ||
      ({
        key,
        value: '',
        visibility: kind === 'group' && (base || key === 'name') ? 'group' : 'self',
      } as Entry);
    changed([...entries.filter((e) => e.key !== key), { ...current, ...patch }]);
  }
  function row(key: string, label: string, custom = false) {
    const item = entries.find((e) => e.key === key);
    return (
      <div className="qq-profile-row" key={key}>
        <div className="qq-profile-value">
          {custom && (
            <label className="qq-field">
              <span>记忆标题</span>
              <Input
                aria-label={`记忆标题 ${key}`}
                maxLength={80}
                value={item?.title || ''}
                onChange={(e) => update(key, { title: e.target.value })}
              />
            </label>
          )}
          <label className="qq-field">
            <span>{label}</span>
            {key === 'name' || key === 'aliases' ? (
              <Input
                maxLength={2000}
                value={item?.value || ''}
                onChange={(e) => update(key, { value: e.target.value })}
              />
            ) : (
              <textarea
                rows={2}
                maxLength={2000}
                value={item?.value || ''}
                onChange={(e) => update(key, { value: e.target.value })}
              />
            )}
          </label>
        </div>
        {kind === 'group' && subject && (
          <label className="qq-field qq-visibility">
            <span>{label}使用范围</span>
            <select
              aria-label={`${label}使用范围`}
              value={item?.visibility || (key === 'name' ? 'group' : 'self')}
              onChange={(e) => update(key, { visibility: e.target.value as Entry['visibility'] })}
            >
              <option value="group">本群可用</option>
              <option value="self">仅回复该成员</option>
            </select>
          </label>
        )}
        {custom && (
          <Button variant="ghost" onClick={() => changed(entries.filter((e) => e.key !== key))}>
            删除条目
          </Button>
        )}
      </div>
    );
  }
  return (
    <section aria-label="手动档案">
      <h3>
        {base ? '群资料' : '个人档案'} <small>管理员手动维护</small>
      </h3>
      <p>
        {base
          ? '仅用于本群回复与摘要理解背景，不作为历史事件证据。'
          : '仅用于当前 QQ 场景，不会自动分享到其他私聊、群或 Web。'}{' '}
        手动资料优先于自动记忆。
      </p>
      {kind === 'group' && subject && (
        <p>“仅回复该成员”仍是群内公开回复，并非保密私聊；称呼默认本群可用，其他条目默认仅回复本人。</p>
      )}
      {error && <p role="alert">{error}</p>}
      {notice && <p role="status">{notice}</p>}
      {!saved ? (
        <p>正在读取档案…</p>
      ) : (
        <fieldset disabled={busy} className="qq-profile-fields">
          {fields.slice(0, base ? 4 : 2).map(([key, label]) => row(key, label))}
          {!base && (
            <details>
              <summary>
                更多资料 ·{' '}
                {
                  entries.filter((e) => person.slice(2).some(([key]) => key === e.key) && e.value.trim())
                    .length
                }{' '}
                项已填写
              </summary>
              {fields.slice(2).map(([key, label]) => row(key, label))}
            </details>
          )}
          {!base && (
            <>
              <h4>自定义记忆</h4>
              {entries.filter((e) => e.key.startsWith('custom_')).map((e) => row(e.key, '记忆内容', true))}
              <Button
                variant="outline"
                disabled={entries.length >= 40}
                onClick={() =>
                  changed([
                    ...entries,
                    {
                      key: `custom_${crypto.randomUUID().replaceAll('-', '').slice(0, 28)}`,
                      title: '',
                      value: '',
                      visibility: 'self',
                    },
                  ])
                }
              >
                新增记忆
              </Button>
            </>
          )}
          <div className="qq-actions qq-save-row">
            <Button
              disabled={!dirty}
              onClick={async () => {
                setBusy(true);
                setError('');
                setNotice('');
                try {
                  const result = await request<Profile>(path, {
                    method: 'PUT',
                    body: JSON.stringify({
                      revision: saved.revision,
                      entries: entries
                        .filter((e) => e.value.trim())
                        .map((e) => ({ ...e, value: e.value.trim() })),
                    }),
                  });
                  if (!active.current) return;
                  setSaved(result);
                  setEntries(result.entries);
                  setDirty(false);
                  onDirty(false);
                  setNotice('资料已保存；下一次回复使用新资料。');
                } catch (e) {
                  setError((e as Error).message);
                } finally {
                  setBusy(false);
                }
              }}
            >
              保存资料
            </Button>
            <span>{dirty ? '有未保存的修改' : `已保存 · 修订 ${saved.revision}`}</span>
            <Button
              variant="ghost"
              onClick={() => {
                if (!dirty || window.confirm('放弃当前草稿并重新读取？')) {
                  setReload((v) => v + 1);
                  setSaved(null);
                  setDirty(false);
                  onDirty(false);
                }
              }}
            >
              重新读取
            </Button>
            <Button
              variant="ghost"
              disabled={!saved.entries.length}
              onClick={async () => {
                if (!window.confirm('删除本档案全部手动资料？自动记忆和聊天记录仍保留。')) return;
                setBusy(true);
                setError('');
                try {
                  const result = await request<Profile>(path + `&revision=${saved.revision}`, {
                    method: 'DELETE',
                  });
                  if (!active.current) return;
                  setSaved(result);
                  setEntries([]);
                  setDirty(false);
                  onDirty(false);
                  setNotice('手动资料已删除，自动记忆保留。');
                } catch (e) {
                  setError((e as Error).message);
                } finally {
                  setBusy(false);
                }
              }}
            >
              清空手动资料
            </Button>
          </div>
        </fieldset>
      )}
      <p>
        删改手动资料不会自动清除历史发言与自动事实；可在下方自动记忆中核对、删除冲突内容。资料过多时仅选用与本轮相关且预算内的完整条目。
      </p>
      {!base && (
        <AutoMemory
          key={`${kind}/${target}/${subject}`}
          kind={kind}
          target={target}
          subject={subject}
          bot={saved?.bot || ''}
        />
      )}
    </section>
  );
}

function AutoMemory({
  kind,
  target,
  subject,
  bot,
}: {
  kind: Kind;
  target: string;
  subject: string;
  bot: string;
}) {
  const [open, setOpen] = useState(false),
    [key, setKey] = useState(''),
    [error, setError] = useState(''),
    [revision, setRevision] = useState(0),
    [busy, setBusy] = useState(false);
  const [data, setData] = useState<{
    memories: { id: string; key: string; value: string }[];
    messages: { id: string; role: string; content: string }[];
  } | null>(null);
  useEffect(() => {
    if (!open || !bot) return;
    const abort = new AbortController();
    void request<{ key: string }[]>('/qq/scopes', { signal: abort.signal })
      .then(async (scopes) => {
        const scope = scopes.find((item) => {
          const [b, k, t, a] = item.key.split(':');
          return b === bot && k === kind && t === target && a === (kind === 'group' ? subject : '');
        });
        if (!scope) {
          if (!abort.signal.aborted) {
            setKey('');
            setData({ memories: [], messages: [] });
          }
          return;
        }
        const next = await request<typeof data>(`/qq/scope?key=${encodeURIComponent(scope.key)}`, {
          signal: abort.signal,
        });
        if (!abort.signal.aborted) {
          setKey(scope.key);
          setData(next);
          setError('');
        }
      })
      .catch((e) => {
        if (!abort.signal.aborted) setError(e.message);
      });
    return () => abort.abort();
  }, [open, bot, kind, target, subject, revision]);
  async function remove(path: string, message: string) {
    if (!window.confirm(message)) return;
    setBusy(true);
    try {
      await request(path, { method: 'DELETE' });
      setRevision((v) => v + 1);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <details onToggle={(e) => setOpen(e.currentTarget.open)}>
      <summary>自动记忆与对话 · 来自聊天整理</summary>
      {kind === 'private' && <p>绑定为主人的私聊继续与 Web 共享自动私人记忆；上方手动资料仅限 QQ。</p>}
      {error && <p role="alert">{error}</p>}
      {!data ? (
        <p>展开后读取…</p>
      ) : (
        <>
          {!data.memories.length && <p>尚无自动记忆。</p>}
          {data.memories.map((item) => (
            <div className="qq-memory" key={item.id}>
              <span>
                {item.key}：{item.value}
              </span>
              <Button
                variant="ghost"
                disabled={busy}
                onClick={() =>
                  void remove(
                    `/qq/scope/memories/${item.id}?key=${encodeURIComponent(key)}`,
                    '删除此自动记忆并建立遗忘约束？',
                  )
                }
              >
                删除自动记忆
              </Button>
            </div>
          ))}
          <details>
            <summary>最近 100 条对话</summary>
            {key && (
              <Button
                variant="ghost"
                disabled={busy}
                onClick={() =>
                  void remove(
                    `/qq/scope/history?key=${encodeURIComponent(key)}`,
                    '清除此 QQ 对话？手动资料和独立记忆保留。',
                  )
                }
              >
                清除此 QQ 对话
              </Button>
            )}
            {data.messages.map((item) => (
              <p key={item.id} className="qq-message">
                <strong>{item.role === 'user' ? '发言人' : '小光'}：</strong>
                {item.content}
              </p>
            ))}
          </details>
        </>
      )}
    </details>
  );
}
