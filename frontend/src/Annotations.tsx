import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from 'react';
import { ContextMenu, Popover } from 'radix-ui';
import { MessageSquarePlus, Pencil, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { request } from './api';
import './annotations.css';

export type AnnotationSource = { kind: 'attachment' | 'artifact' | 'message'; id: string; version: string };
export type AnnotationAnchor = {
  source: AnnotationSource;
  target_id: string;
  name?: string;
  location?: string;
  quote?: string;
  rect?: [number, number, number, number];
  regions?: { page: number; rect: [number, number, number, number] }[];
  text_origin?: 'native' | 'ocr';
};
export type AnnotationDraft = AnnotationAnchor & {
  id: string;
  comment: string;
  status: string;
  updated_at: string;
};
export type AnnotationSubmission = { ids: string[]; scope: string };
type ViewAnchor = { getBoundingClientRect: () => DOMRect };
type Editor = AnnotationAnchor & { id?: string; comment: string; token?: string };
type State = {
  drafts: AnnotationDraft[];
  begin: (prepare: () => Promise<AnnotationAnchor>, quote?: string, view?: ViewAnchor) => Promise<void>;
  edit: (draft: AnnotationDraft, view?: ViewAnchor, hover?: boolean) => void;
  remove: (id: string) => Promise<void>;
  submitted: (ids: string[]) => void;
  submission: () => Promise<AnnotationSubmission | undefined>;
  sending: boolean;
  setSending: (value: boolean) => void;
  error: string;
};
const Context = createContext<State | null>(null);
export const useAnnotations = () => useContext(Context);

function initialScope() {
  try {
    const saved = sessionStorage.getItem('shunguang.annotation-draft-scope');
    if (saved && /^[a-zA-Z0-9_-]{1,80}$/.test(saved)) return saved;
  } catch {
    /* In-memory drafts still work when session storage is disabled. */
  }
  return crypto.randomUUID();
}

export function AnnotationProvider({
  conversationId,
  children,
}: {
  conversationId: string | null;
  children: ReactNode;
}) {
  const [newScope, setNewScope] = useState(initialScope);
  const previous = useRef(conversationId);
  const [drafts, setDrafts] = useState<AnnotationDraft[]>([]);
  const [editor, setEditor] = useState<Editor | null>(null);
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const [sending, setSending] = useState(false);
  const viewAnchor = useRef<ViewAnchor | null>(null);
  const hoverOpen = useRef(false);
  const saveLock = useRef(false);
  const opening = useRef(0);
  const active = useRef(editor);
  active.current = editor;
  const scope = conversationId ?? `new:${newScope}`;
  const [draftOwner, setDraftOwner] = useState(scope);
  const visibleDrafts = draftOwner === scope ? drafts : [];
  const current = useRef(scope);
  const changes = useRef(new Map<string, AnnotationDraft | null>());
  current.current = scope;
  useEffect(() => {
    if (previous.current && !conversationId) setNewScope(crypto.randomUUID());
    previous.current = conversationId;
  }, [conversationId]);
  useEffect(() => {
    try {
      sessionStorage.setItem('shunguang.annotation-draft-scope', newScope);
    } catch {
      /* Optional persistence. */
    }
  }, [newScope]);
  useEffect(() => {
    const abort = new AbortController();
    const localChanges = new Map<string, AnnotationDraft | null>();
    changes.current = localChanges;
    setDraftOwner(scope);
    setDrafts([]);
    setEditor(null);
    setError('');
    const query = conversationId
      ? `conversation_id=${encodeURIComponent(conversationId)}`
      : `draft_scope=${encodeURIComponent(newScope)}`;
    void request<AnnotationDraft[]>(`/work/annotations?${query}`, { signal: abort.signal })
      .then((value) => {
        if (!abort.signal.aborted) {
          const merged = new Map<string, AnnotationDraft>(
            (Array.isArray(value) ? value : []).map((item) => [item.id, item]),
          );
          for (const [id, draft] of localChanges) {
            if (draft) merged.set(id, draft);
            else merged.delete(id);
          }
          setDrafts([...merged.values()]);
        }
      })
      .catch((failure: Error) => {
        if (!abort.signal.aborted) setError(failure.message);
      });
    return () => abort.abort();
  }, [conversationId, newScope]);
  async function begin(prepare: () => Promise<AnnotationAnchor>, quote = '', view?: ViewAnchor) {
    const ticket = ++opening.current;
    const expected = scope;
    if (sending || saveLock.current) return;
    if (active.current && !(await save())) return;
    setError('');
    try {
      const anchor = await prepare();
      if (current.current === expected && opening.current === ticket) {
        viewAnchor.current = view ?? null;
        hoverOpen.current = false;
        setEditor({ ...anchor, quote: quote || anchor.quote || '', comment: '', token: crypto.randomUUID() });
      }
    } catch (failure) {
      if (current.current === expected) setError((failure as Error).message);
    }
  }
  async function save() {
    const editor = active.current;
    if (saveLock.current) return false;
    if (!editor) return true;
    if (!editor.comment.trim()) {
      if (editor.id) {
        setError('批注不能为空；如需删除，请使用草稿列表的删除按钮。');
        return false;
      }
      setEditor(null);
      return true;
    }
    if (
      editor.id &&
      visibleDrafts.some((draft) => draft.id === editor.id && draft.comment === editor.comment)
    ) {
      setEditor(null);
      return true;
    }
    const expected = scope;
    saveLock.current = true;
    setSaving(true);
    setError('');
    try {
      const value = await request<AnnotationDraft>(
        editor.id ? `/work/annotations/${editor.id}` : '/work/annotations',
        {
          method: editor.id ? 'PATCH' : 'POST',
          body: JSON.stringify(
            editor.id
              ? { comment: editor.comment }
              : {
                  conversation_id: conversationId,
                  draft_scope: conversationId ? '' : newScope,
                  source: editor.source,
                  target_id: editor.target_id,
                  quote: editor.quote || '',
                  ...(editor.rect ? { rect: editor.rect } : {}),
                  ...(editor.regions ? { regions: editor.regions } : {}),
                  ...(editor.text_origin ? { text_origin: editor.text_origin } : {}),
                  comment: editor.comment,
                },
          ),
        },
      );
      if (current.current === expected) {
        changes.current.set(value.id, value);
        setDrafts((items) =>
          editor.id ? items.map((item) => (item.id === editor.id ? value : item)) : [...items, value],
        );
        setEditor((current) => (current?.token === editor.token ? null : current));
      }
      return true;
    } catch (failure) {
      if (current.current === expected) setError((failure as Error).message);
      return false;
    } finally {
      saveLock.current = false;
      setSaving(false);
    }
  }
  async function remove(id: string) {
    const expected = scope;
    try {
      await request(`/work/annotations/${encodeURIComponent(id)}`, { method: 'DELETE' });
      if (current.current === expected) {
        changes.current.set(id, null);
        setDrafts((items) => items.filter((item) => item.id !== id));
      }
    } catch (failure) {
      if (current.current === expected) setError((failure as Error).message);
    }
  }
  return (
    <Context.Provider
      value={{
        drafts: visibleDrafts,
        begin,
        edit: (draft, view, hover = false) => {
          if (
            sending ||
            saveLock.current ||
            (hover && active.current && (!hoverOpen.current || active.current.id === draft.id))
          )
            return;
          const expected = scope;
          const ticket = ++opening.current;
          void (async () => {
            if (active.current && !(await save())) return;
            if (current.current !== expected || opening.current !== ticket) return;
            viewAnchor.current =
              view ?? document.querySelector<HTMLElement>(`[data-annotation-id="${draft.id}"]`);
            hoverOpen.current = hover;
            setError('');
            setEditor({ ...draft, token: crypto.randomUUID() });
          })();
        },
        remove,
        sending: sending || saving,
        setSending,
        error,
        submitted: (ids) => {
          ids.forEach((id) => changes.current.set(id, null));
          setDrafts((items) => items.filter((item) => !ids.includes(item.id)));
        },
        submission: async () => {
          const expected = scope;
          if (!(await save()) || current.current !== expected)
            throw new Error('批注尚未保存，请保存成功后再发送。');
          const items = new Map(visibleDrafts.map((draft) => [draft.id, draft]));
          for (const [id, draft] of changes.current) {
            if (draft) items.set(id, draft);
            else items.delete(id);
          }
          return items.size ? { ids: [...items.keys()], scope: newScope } : undefined;
        },
      }}
    >
      {children}
      <Popover.Root
        modal={false}
        open={!!editor}
        onOpenChange={(open) => {
          if (!open) void save();
        }}
      >
        <Popover.Anchor virtualRef={viewAnchor} />
        <Popover.Portal>
          <Popover.Content
            className="annotation-bubble"
            side="bottom"
            align="start"
            sideOffset={6}
            collisionPadding={12}
            updatePositionStrategy="always"
            onOpenAutoFocus={(event) => {
              if (hoverOpen.current) event.preventDefault();
            }}
            onCloseAutoFocus={(event) => event.preventDefault()}
            onInteractOutside={(event) => {
              event.preventDefault();
              void save();
            }}
            onEscapeKeyDown={(event) => {
              event.preventDefault();
              void save();
            }}
            aria-label={editor?.id ? '编辑批注' : '添加批注'}
          >
            <strong>{editor?.id ? '编辑批注' : '添加批注'}</strong>
            <small>
              {editor?.name} · {editor?.location}。保存为草稿，确认发送后再修改。
            </small>
            {editor?.quote && (
              <blockquote className="annotation-quote">{editor.quote.slice(0, 1000)}</blockquote>
            )}
            <label className="field">
              修改意见
              <textarea
                rows={3}
                disabled={saving || sending}
                maxLength={2000}
                value={editor?.comment ?? ''}
                onChange={(event) => {
                  hoverOpen.current = false;
                  setEditor((value) => value && { ...value, comment: event.target.value });
                }}
              />
            </label>
            {error && <p role="alert">{error}</p>}
            <div className="work-actions">
              <Button type="button" disabled={saving || !editor?.comment.trim()} onClick={() => void save()}>
                保存批注草稿
              </Button>
              <Button type="button" variant="outline" disabled={saving} onClick={() => setEditor(null)}>
                取消
              </Button>
            </div>
          </Popover.Content>
        </Popover.Portal>
      </Popover.Root>
    </Context.Provider>
  );
}

export function AnnotationPins({
  anchor,
  messageId,
  draftId,
}: {
  anchor?: AnnotationAnchor;
  messageId?: string;
  draftId?: string;
}) {
  const state = useAnnotations();
  if (!state) return null;
  return (
    <span className="annotation-pins">
      {state.drafts.map((draft, index) => {
        const matches = anchor
          ? draft.source.kind === anchor.source.kind &&
            draft.source.id === anchor.source.id &&
            draft.source.version === anchor.source.version &&
            draft.target_id === anchor.target_id
          : draft.source.kind === 'message' && draft.source.id === messageId;
        if (!matches || (draftId && draft.id !== draftId)) return null;
        return (
          <button
            key={draft.id}
            type="button"
            className="annotation-pin"
            data-annotation-id={draft.id}
            aria-label={`批注 ${index + 1}`}
            title={draft.comment}
            disabled={state.sending}
            onMouseEnter={(event) => state.edit(draft, event.currentTarget, true)}
            onClick={(event) => {
              event.stopPropagation();
              state.edit(draft, event.currentTarget);
            }}
          >
            {index + 1}
          </button>
        );
      })}
    </span>
  );
}

export function AnnotationTarget({
  prepare,
  anchor,
  messageId,
  label,
  children,
}: {
  prepare: () => Promise<AnnotationAnchor>;
  anchor?: AnnotationAnchor;
  messageId?: string;
  label: string;
  children: ReactNode;
}) {
  const state = useAnnotations();
  const host = useRef<HTMLDivElement>(null);
  const quote = useRef('');
  const [loaded, setLoaded] = useState<AnnotationAnchor>();
  function capture() {
    const selection = window.getSelection();
    quote.current =
      selection && host.current?.contains(selection.anchorNode) && host.current.contains(selection.focusNode)
        ? selection.toString().slice(0, 20000)
        : '';
  }
  if (!state) return <>{children}</>;
  const begin = () => {
    void state.begin(
      async () => {
        const value = await prepare();
        setLoaded(value);
        return value;
      },
      quote.current,
      host.current ?? undefined,
    );
  };
  return (
    <ContextMenu.Root>
      <ContextMenu.Trigger asChild>
        <div
          ref={host}
          className="annotation-target"
          onContextMenuCapture={capture}
          onKeyDownCapture={(event) => {
            if (event.key === 'ContextMenu' || (event.shiftKey && event.key === 'F10')) capture();
          }}
        >
          {children}
          <AnnotationPins anchor={anchor ?? loaded} messageId={messageId} />
          <button
            type="button"
            className="annotation-trigger icon-button"
            aria-label={`批注${label}`}
            title="添加批注"
            disabled={state.sending}
            onPointerDown={capture}
            onClick={begin}
          >
            <MessageSquarePlus size={15} />
          </button>
        </div>
      </ContextMenu.Trigger>
      <ContextMenu.Portal>
        <ContextMenu.Content
          className="annotation-menu"
          aria-label="选区操作"
          onCloseAutoFocus={(event) => event.preventDefault()}
        >
          <ContextMenu.Item disabled={state.sending} onSelect={begin}>
            添加评论
          </ContextMenu.Item>
          <ContextMenu.Item
            disabled={!navigator.clipboard}
            onSelect={() => {
              void navigator.clipboard?.writeText(quote.current).catch(() => {});
            }}
          >
            复制选中文字
          </ContextMenu.Item>
        </ContextMenu.Content>
      </ContextMenu.Portal>
    </ContextMenu.Root>
  );
}

export function AnnotationTray() {
  const state = useAnnotations();
  if (!state) return null;
  return (
    <>
      {state.error && (
        <p className="space-note" role="status">
          {state.error}
        </p>
      )}
      {!!state.drafts.length && (
        <details className="annotation-tray" open>
          <summary>
            待发送批注（{state.drafts.length}）<span>随下一条消息统一提交</span>
          </summary>
          <div className="annotation-drafts">
            {state.drafts.map((draft, index) => (
              <article key={draft.id}>
                <div>
                  <strong>
                    {index + 1}. {draft.name} · {draft.location}
                  </strong>
                  <p>{draft.comment}</p>
                </div>
                <button
                  type="button"
                  className="icon-button"
                  disabled={state.sending}
                  aria-label={`编辑批注 ${index + 1}`}
                  onClick={() => state.edit(draft)}
                >
                  <Pencil size={14} />
                </button>
                <button
                  type="button"
                  className="icon-button"
                  disabled={state.sending}
                  aria-label={`删除批注 ${index + 1}`}
                  onClick={() => void state.remove(draft.id)}
                >
                  <Trash2 size={14} />
                </button>
              </article>
            ))}
          </div>
        </details>
      )}
    </>
  );
}

export function ReplyAnnotations({ items }: { items: unknown }) {
  if (!Array.isArray(items) || !items.length) return null;
  return (
    <details className="reply-annotations">
      <summary>本次涉及 {items.length} 条批注</summary>
      <ol>
        {items.map((item) => (
          <li key={String(item.id)}>
            {String(item.name ?? '')} · {String(item.location ?? '')}：{String(item.comment ?? '')}
          </li>
        ))}
      </ol>
    </details>
  );
}
