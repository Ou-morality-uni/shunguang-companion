import { useId, useState, useEffect, useRef } from 'react';
import { motion, useReducedMotion } from 'motion/react';
import { MessageSquare, Trash2 } from 'lucide-react';
import type { Conversation } from './api';
import { Button } from './components/ui/button';

export function ConversationHistory({
  conversations,
  active,
  disabled,
  onSelect,
  onDelete,
}: {
  conversations: Conversation[];
  active: string | null;
  disabled: boolean;
  onSelect: (id: string) => void;
  onDelete: (id: string) => Promise<void>;
}) {
  const [confirm, setConfirm] = useState<string | null>(null);
  const confirmButton = useRef<HTMLButtonElement>(null);
  const triggerButton = useRef<HTMLButtonElement | null>(null);
  const container = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (confirm) confirmButton.current?.focus();
    else if (triggerButton.current?.isConnected) triggerButton.current.focus();
    else if (triggerButton.current)
      container.current?.querySelector<HTMLButtonElement>('button:not(:disabled)')?.focus();
  }, [confirm]);
  const highlightId = useId(),
    reduced = useReducedMotion();
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState('');
  async function remove(id: string) {
    setDeleting(true);
    setError('');
    try {
      await onDelete(id);
      setConfirm(null);
    } catch (failure) {
      setError((failure as Error).message);
    } finally {
      setDeleting(false);
    }
  }
  return (
    <div className="history-list" ref={container}>
      {!conversations.length && (
        <div className="empty-history">
          <MessageSquare size={17} />
          <p>
            故事，从一句你好开始。
            <br />
            <span>还没有对话记录</span>
          </p>
        </div>
      )}
      {conversations.map((item) => (
        <div key={item.id}>
          <div className="history-row">
            <button
              disabled={disabled || deleting}
              className={`history-item ${item.id === active ? 'active' : ''}`}
              onClick={() => onSelect(item.id)}
            >
              {item.id === active && (
                <motion.span
                  aria-hidden="true"
                  className="selection-glide"
                  layoutId={highlightId}
                  transition={{ duration: reduced ? 0 : 0.22 }}
                />
              )}
              <MessageSquare size={14} />
              <span>{item.title}</span>
            </button>
            <button
              className="icon-button"
              disabled={disabled || deleting}
              aria-label={`删除对话 ${item.title}`}
              aria-expanded={confirm === item.id}
              onClick={(event) => {
                triggerButton.current = event.currentTarget;
                setConfirm(item.id);
                setError('');
              }}
            >
              <Trash2 size={14} />
            </button>
          </div>
          {confirm === item.id && (
            <div className="delete-confirm" role="group" aria-label="确认删除对话">
              <p>
                删除这段对话、消息及其独占附件和成果？其他对话或任务仍引用的文件、工作区原文件与已确认的长期记忆会保留。历史备份和另存副本不随之删除。
              </p>
              <Button
                ref={confirmButton}
                disabled={disabled || deleting}
                variant="outline"
                onClick={() => void remove(item.id)}
              >
                确认删除
              </Button>
              <button disabled={deleting} className="text-link" onClick={() => setConfirm(null)}>
                取消
              </button>
              {error && <p role="alert">{error}</p>}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
