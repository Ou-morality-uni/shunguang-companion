import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from 'react';
import { ContextMenu } from 'radix-ui';
import { MessageSquarePlus, Pencil, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog';
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
type Editor = AnnotationAnchor & { id?: string; comment: string };
type State = {
  drafts: AnnotationDraft[];
  begin: (prepare: () => Promise<AnnotationAnchor>, quote?: string) => Promise<void>;
  edit: (draft: AnnotationDraft) => void;
  remove: (id: string) => Promise<void>;
  submitted: (ids: string[]) => void;
  submission: () => AnnotationSubmission | undefined;
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
  async function begin(prepare: () => Promise<AnnotationAnchor>, quote = '') {
    const expected = scope;
    setError('');
    try {
      const anchor = await prepare();
      if (current.current === expected)
        setEditor({ ...anchor, quote: quote || anchor.quote || '', comment: '' });
    } catch (failure) {
      if (current.current === expected) setError((failure as Error).message);
    }
  }
  async function save() {
    if (!editor || !editor.comment.trim() || saving) return;
    const expected = scope;
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
        setEditor(null);
      }
    } catch (failure) {
      if (current.current === expected) setError((failure as Error).message);
    } finally {
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
        edit: setEditor,
        remove,
        sending,
        setSending,
        error,
        submitted: (ids) => {
          ids.forEach((id) => changes.current.set(id, null));
          setDrafts((items) => items.filter((item) => !ids.includes(item.id)));
        },
        submission: () =>
          visibleDrafts.length ? { ids: visibleDrafts.map((item) => item.id), scope: newScope } : undefined,
      }}
    >
      {children}
      <Dialog
        open={!!editor}
        onOpenChange={(open) => {
          if (!open && !saving) setEditor(null);
        }}
      >
        <DialogContent className="annotation-dialog">
          <DialogTitle>{editor?.id ? '编辑批注' : '添加批注'}</DialogTitle>
          <DialogDescription>
            {editor?.name} · {editor?.location}。保存为草稿，确认发送后再修改。
          </DialogDescription>
          {editor?.quote && (
            <blockquote className="annotation-quote">{editor.quote.slice(0, 1000)}</blockquote>
          )}
          <label className="field">
            修改意见
            <textarea
              autoFocus
              rows={4}
              maxLength={2000}
              value={editor?.comment ?? ''}
              onChange={(event) => setEditor((value) => value && { ...value, comment: event.target.value })}
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
        </DialogContent>
      </Dialog>
    </Context.Provider>
  );
}

export function AnnotationTarget({
  prepare,
  label,
  children,
}: {
  prepare: () => Promise<AnnotationAnchor>;
  label: string;
  children: ReactNode;
}) {
  const state = useAnnotations();
  const host = useRef<HTMLDivElement>(null);
  const quote = useRef('');
  function capture() {
    const selection = window.getSelection();
    quote.current =
      selection && host.current?.contains(selection.anchorNode) && host.current.contains(selection.focusNode)
        ? selection.toString().slice(0, 20000)
        : '';
  }
  if (!state) return <>{children}</>;
  const begin = () => {
    void state.begin(prepare, quote.current);
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
        <ContextMenu.Content className="annotation-menu" aria-label="选区操作">
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
