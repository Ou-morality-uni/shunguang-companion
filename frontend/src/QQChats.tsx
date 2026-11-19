import { useEffect, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { request, type Sticker } from './api';
import { DocumentMarkdown } from './DocumentMarkdown';
import { ResourceImage } from './ResourceImage';
import { MessageSticker } from './MessageSticker';

export type Chat = { kind: 'private' | 'group'; target: string; name: string; count: number; stamp: number };
type Entry = {
  id: string;
  author: string;
  name: string;
  stamp: number;
  text: string;
  reply: string;
  state: string;
  error: string;
  sticker: Sticker | null;
  images: { id: string; url: string | null; description: string; error: string }[];
};
type Page = { items: Entry[]; next_cursor: string; has_more: boolean; stickers?: boolean };
const labels: Record<string, string> = {
  queued: '等待处理',
  processing: '正在回复',
  replied: '已发送',
  failed: '处理失败',
  uncertain: '发送结果待确认',
  collected: '仅采集',
  quiet: '保持安静',
  limited: '已限流或消息过期',
  revoked: '权限已撤销',
};
const time = (stamp: number) =>
  new Date(stamp * 1000).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false });

export function QQChats({ chat }: { chat?: Chat } = {}) {
  const [savingSticker, setSavingSticker] = useState(false),
    [switchNotice, setSwitchNotice] = useState('');
  const [search, setSearch] = useState(''),
    [offset, setOffset] = useState(0);
  const [list, setList] = useState<{ items: Chat[]; total: number }>({ items: [], total: 0 });
  const [localSelected, setSelected] = useState<Chat | null>(null),
    [page, setPage] = useState<Page | null>(null);
  const [cursor, setCursor] = useState(''),
    [revision, setRevision] = useState(0),
    [error, setError] = useState('');
  const selected = chat ?? localSelected;
  useEffect(() => {
    if (chat) return;
    const abort = new AbortController();
    const load = () =>
      request<{ items: Chat[]; total: number }>(
        `/qq/chats?search=${encodeURIComponent(search)}&offset=${offset}`,
        { signal: abort.signal },
      )
        .then((value) => {
          if (!abort.signal.aborted) setList(value);
        })
        .catch((e) => {
          if (!abort.signal.aborted) setError(e.message);
        });
    void load();
    const timer = window.setInterval(() => {
      if (!document.hidden) void load();
    }, 5000);
    return () => {
      abort.abort();
      window.clearInterval(timer);
    };
  }, [search, offset, revision, chat]);
  useEffect(() => {
    if (!selected) return;
    const abort = new AbortController();
    const load = () =>
      request<Page>(`/qq/chats/${selected.kind}/${selected.target}?before=${encodeURIComponent(cursor)}`, {
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
    void load();
    const timer = cursor
      ? undefined
      : window.setInterval(() => {
          if (!document.hidden) void load();
        }, 5000);
    return () => {
      abort.abort();
      if (timer) window.clearInterval(timer);
    };
  }, [selected, cursor, revision]);
  const latest = page?.items.at(-1);
  return (
    <div className="qq-chat-layout">
      {!chat && (
        <section className="qq-card">
          <h2>QQ 聊天记录</h2>
          <p>仅展示开始采集后保存的记录；与 Web 最近对话分开，本人私人记忆继续共享。</p>
          <FieldSearch
            value={search}
            change={(value) => {
              setSearch(value);
              setOffset(0);
            }}
          />
          <div className="qq-peer-list">
            {list.items.map((item) => (
              <Button
                key={`${item.kind}/${item.target}`}
                variant="outline"
                aria-pressed={selected?.kind === item.kind && selected.target === item.target}
                disabled={savingSticker}
                onClick={() => {
                  setSelected(item);
                  setPage(null);
                  setCursor('');
                  setError('');
                  setSwitchNotice('');
                }}
              >
                {item.name} · {item.kind === 'private' ? '私聊' : '群聊'} · {item.target} · {item.count} 条
              </Button>
            ))}
          </div>
          {!list.total && <p>尚无已采集的 QQ 聊天记录。</p>}
          <div className="qq-actions">
            <Button variant="outline" disabled={!offset} onClick={() => setOffset(Math.max(0, offset - 30))}>
              上一页
            </Button>
            <span>{list.total} 个聊天</span>
            <Button
              variant="outline"
              disabled={offset + 30 >= list.total}
              onClick={() => setOffset(offset + 30)}
            >
              下一页
            </Button>
          </div>
        </section>
      )}
      {error && (
        <p role="alert" className="error-banner">
          {error}
        </p>
      )}
      {selected && (
        <section className="qq-card qq-chat-thread">
          {!chat && (
            <h2>
              {selected.name} · {selected.kind === 'private' ? 'QQ 私聊' : 'QQ 群聊'} · {selected.target}
            </h2>
          )}
          {!chat && page && (
            <label className="qq-toggle">
              <input
                type="checkbox"
                checked={page.stickers ?? true}
                disabled={savingSticker}
                onChange={async (e) => {
                  const enabled = e.target.checked;
                  setSavingSticker(true);
                  setSwitchNotice('');
                  try {
                    const result = await request<{ stickers: boolean }>(
                      `/qq/chats/${selected.kind}/${selected.target}/stickers`,
                      {
                        method: 'PATCH',
                        body: JSON.stringify({ enabled }),
                      },
                    );
                    setPage((previous) => (previous ? { ...previous, stickers: result.stickers } : previous));
                    setSwitchNotice(
                      result.stickers
                        ? '已开启本聊天的表情包'
                        : '已关闭本聊天的表情包，文字回复和图片识别不受影响',
                    );
                    setRevision((v) => v + 1);
                  } catch (e) {
                    setError((e as Error).message);
                  } finally {
                    setSavingSticker(false);
                  }
                }}
              />
              回复附带表情包
            </label>
          )}
          {switchNotice && <p role="status">{switchNotice}</p>}
          {!cursor && page && (
            <section aria-label="最近一条消息的处理状态" className="qq-chat-reply">
              <strong>最近一条消息的处理状态</strong>
              <div role="status">
                {latest ? (
                  <>
                    <p>
                      {latest.state === 'processing' && latest.reply
                        ? '已生成，正在投递'
                        : labels[latest.state] || latest.state}{' '}
                      · {time(latest.stamp)}
                    </p>
                    {latest.error && <p>{latest.error}</p>}
                  </>
                ) : (
                  <p>还没有已采集的消息，请检查 QQ 连接及此聊天的采集设置。</p>
                )}
              </div>
            </section>
          )}
          <div className="qq-actions">
            <Button
              variant="outline"
              onClick={() => {
                if (cursor) setPage(null);
                setCursor('');
                setRevision((v) => v + 1);
              }}
            >
              最新消息
            </Button>
            <Button
              variant="outline"
              disabled={!page?.has_more}
              onClick={() => {
                if (page) {
                  setCursor(page.next_cursor);
                  setPage(null);
                }
              }}
            >
              更早消息
            </Button>
          </div>
          <p>查看模式。最新一页每 5 秒刷新；“已生成”不代表已送达，发送待确认时请以 QQ 客户端为准。</p>
          {!page ? (
            <p role="status">正在读取聊天…</p>
          ) : !page.items.length ? (
            <p>这个时间段没有已保存的消息。</p>
          ) : (
            page.items.map((item) => (
              <article key={item.id} className="qq-chat-entry">
                <div className="qq-chat-meta">
                  {item.name || item.author}（{item.author}） · {time(item.stamp)}
                </div>
                <DocumentMarkdown text={item.text.replaceAll('[图片，尚未识别]', '[图片]')} />
                {item.images.map((image) => (
                  <div key={image.id} className="qq-chat-image">
                    {image.url?.startsWith(`/api/qq/chats/${selected.kind}/${selected.target}/images/`) && (
                      <ResourceImage src={image.url} alt="QQ 收到的图片" />
                    )}
                    {image.description && (
                      <details>
                        <summary>图片识别结果</summary>
                        <DocumentMarkdown text={image.description} />
                      </details>
                    )}
                    {image.error && <p role="status">{image.error}</p>}
                  </div>
                ))}
                <p className="qq-chat-meta">{labels[item.state] || item.state}</p>
                {item.error && <p role="status">{item.error}</p>}
                {item.reply && (
                  <div className="qq-chat-reply">
                    <strong>叶瞬光</strong>
                    <DocumentMarkdown text={item.reply} />
                    {item.sticker && (
                      <>
                        <MessageSticker sticker={item.sticker} />
                        {item.state !== 'replied' && <small>本次生成的表情包，送达情况尚未确认。</small>}
                      </>
                    )}
                  </div>
                )}
              </article>
            ))
          )}
        </section>
      )}
    </div>
  );
}

function FieldSearch({ value, change }: { value: string; change: (value: string) => void }) {
  return (
    <label className="qq-field">
      <span>搜索 QQ 聊天名称或号码</span>
      <Input value={value} onChange={(e) => change(e.target.value)} />
    </label>
  );
}
