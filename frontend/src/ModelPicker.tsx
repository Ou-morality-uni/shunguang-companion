import { useEffect, useRef, useState, useId } from 'react';
import { Popover } from 'radix-ui';
import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import { Check, ChevronDown, RefreshCw } from 'lucide-react';
import { request, type ConnectionOptions, type ModelChoice, type ModelChoiceOut } from './api';

export const effortLabels: Record<string, string> = {
  off: 'Off',
  on: 'On',
  low: 'Low',
  medium: 'Medium',
  high: 'High',
  xhigh: 'Extra High',
  max: 'Max',
};
const supported = (values: string[]) => {
  const levels = values.filter((value) => !['default', 'off', 'on'].includes(value));
  return levels.length ? levels : values.filter((value) => value !== 'default');
};
const initial = (values: string[]) =>
  ['medium', 'on', 'high', 'low', 'xhigh', 'max', 'off'].find((value) => values.includes(value)) ?? 'default';

export function ModelPicker({
  conversationId,
  disabled,
  onChange,
  onSettings,
  revision,
}: {
  conversationId: string | null;
  disabled: boolean;
  onChange: (choice: ModelChoice | undefined) => void;
  onSettings: () => void;
  revision?: object | null;
}) {
  const highlightId = useId();
  const [highlight, setHighlight] = useState('');
  const [connections, setConnections] = useState<ConnectionOptions[]>([]);
  const [choice, setChoice] = useState<ModelChoiceOut | null>(null);
  const [open, setOpen] = useState(false),
    [loading, setLoading] = useState(true),
    [pending, setPending] = useState(false),
    [refreshing, setRefreshing] = useState(false),
    [error, setError] = useState('');
  const scope = useRef(conversationId);
  scope.current = conversationId;
  const refreshed = useRef(new Set<string>()),
    refreshAbort = useRef<AbortController | null>(null);
  const systemReduced = useReducedMotion();
  const reduced = systemReduced || document.documentElement.dataset.reduceMotion === 'true';
  useEffect(() => {
    const abort = new AbortController();
    refreshAbort.current?.abort();
    refreshed.current.clear();
    setLoading(true);
    setOpen(false);
    setError('');
    setChoice(null);
    setPending(false);
    setRefreshing(false);
    void (async () => {
      try {
        const [groups, selected] = await Promise.all([
          request<ConnectionOptions[]>('/model-options', { signal: abort.signal }),
          request<ModelChoiceOut | null>(
            conversationId ? `/conversations/${conversationId}/model` : '/model-default',
            { signal: abort.signal },
          ),
        ]);
        if (abort.signal.aborted) return;
        setConnections(Array.isArray(groups) ? groups : []);
        const value = selected
          ? {
              ...selected,
              efforts: supported(selected.efforts),
              effort:
                selected.effort === 'default'
                  ? (initial(supported(selected.efforts)) as ModelChoice['effort'])
                  : selected.effort,
            }
          : null;
        setChoice(value);
        onChange(
          value ? { profile_id: value.profile_id, model: value.model, effort: value.effort } : undefined,
        );
      } catch (failure) {
        if (!abort.signal.aborted) setError((failure as Error).message);
      } finally {
        if (!abort.signal.aborted) setLoading(false);
      }
    })();
    return () => {
      abort.abort();
      refreshAbort.current?.abort();
    };
  }, [conversationId, onChange, revision]);
  async function refresh(force = false) {
    const groups = connections.filter(
      (group) => group.configured && (force || !refreshed.current.has(group.id)),
    );
    if (!groups.length || refreshing) return;
    const abort = new AbortController();
    refreshAbort.current?.abort();
    refreshAbort.current = abort;
    setRefreshing(true);
    setError('');
    const results = await Promise.allSettled(
      groups.map(async (group) => {
        const updated = await request<ConnectionOptions>(`/model-options/${group.id}/refresh`, {
          method: 'POST',
          signal: abort.signal,
        });
        if (!abort.signal.aborted && Array.isArray(updated.models)) {
          refreshed.current.add(group.id);
          setConnections((items) => items.map((item) => (item.id === group.id ? updated : item)));
        }
      }),
    );
    if (!abort.signal.aborted) {
      if (results.some((result) => result.status === 'rejected'))
        setError('部分模型目录暂不可用，已保留可用缓存，可稍后刷新。');
      setRefreshing(false);
    }
  }
  async function select(next: ModelChoice, efforts: string[]) {
    const expected = conversationId;
    setPending(true);
    setError('');
    try {
      const saved = conversationId
        ? await request<ModelChoiceOut>(`/conversations/${conversationId}/model`, {
            method: 'PATCH',
            body: JSON.stringify(next),
          })
        : { ...next, configured: true, efforts };
      if (scope.current === expected) {
        setChoice(saved);
        onChange({ profile_id: saved.profile_id, model: saved.model, effort: saved.effort });
      }
    } catch (failure) {
      if (scope.current === expected) setError((failure as Error).message);
    } finally {
      if (scope.current === expected) setPending(false);
    }
  }
  const efforts = supported(choice?.efforts ?? []);
  return (
    <div className="model-picker">
      <Popover.Root
        open={open}
        onOpenChange={(value) => {
          setOpen(value);
          if (value) void refresh();
        }}
      >
        <Popover.Trigger asChild>
          <button
            type="button"
            role="combobox"
            aria-label="当前会话模型"
            aria-haspopup="dialog"
            aria-expanded={open}
            onKeyDown={(event) => {
              if (event.key === 'ArrowDown') {
                event.preventDefault();
                setOpen(true);
                void refresh();
              }
            }}
            disabled={disabled || loading || pending}
            className="model-pill"
          >
            <AnimatePresence mode="wait" initial={false}>
              <motion.span
                key={`${choice?.model}:${choice?.effort}`}
                initial={{ opacity: reduced ? 1 : 0, y: reduced ? 0 : 2 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: reduced ? 1 : 0 }}
                transition={{ duration: reduced ? 0 : 0.12 }}
              >
                {loading ? '读取模型…' : choice?.model || '选择模型'}
                {efforts.length > 0 && choice?.effort && effortLabels[choice.effort]
                  ? ` · ${effortLabels[choice.effort]}`
                  : ''}
              </motion.span>
            </AnimatePresence>
            <ChevronDown size={13} />
          </button>
        </Popover.Trigger>
        <Popover.Portal>
          <Popover.Content
            side="top"
            align="end"
            sideOffset={10}
            collisionPadding={12}
            className="model-menu"
            aria-label="选择模型与思考"
          >
            <div className="model-menu-heading">
              <strong>选择模型</strong>
              <button
                type="button"
                className="icon-button"
                aria-label="刷新模型列表"
                disabled={refreshing}
                onClick={() => void refresh(true)}
              >
                <RefreshCw size={14} className={refreshing ? 'spin' : ''} />
              </button>
            </div>
            <div
              className="model-menu-list"
              role="listbox"
              aria-label="可用模型"
              onKeyDown={(event) => {
                const nodes = Array.from(
                  event.currentTarget.querySelectorAll<HTMLButtonElement>('[role="option"]:not(:disabled)'),
                );
                const index = nodes.indexOf(document.activeElement as HTMLButtonElement);
                const next =
                  event.key === 'ArrowDown'
                    ? (index + 1) % nodes.length
                    : event.key === 'ArrowUp'
                      ? (index - 1 + nodes.length) % nodes.length
                      : event.key === 'Home'
                        ? 0
                        : event.key === 'End'
                          ? nodes.length - 1
                          : -1;
                if (next >= 0) {
                  event.preventDefault();
                  nodes[next]?.focus();
                }
              }}
            >
              {connections.map((group) => (
                <div role="group" aria-label={group.label} key={group.id}>
                  <div className="glide-group">{group.label}</div>
                  {group.models.map((model) => {
                    const active = choice?.profile_id === group.id && choice?.model === model.id;
                    return (
                      <button
                        type="button"
                        role="option"
                        aria-selected={active}
                        disabled={!group.configured || pending}
                        key={model.id}
                        onPointerMove={() => setHighlight(`${group.id}:${model.id}`)}
                        onFocus={() => setHighlight(`${group.id}:${model.id}`)}
                        className={`model-option ${active ? 'selected' : ''}`}
                        onClick={() => {
                          const levels = supported(model.efforts);
                          const preferred =
                            (model as typeof model & { initial_effort?: string }).initial_effort ??
                            initial(levels);
                          void select(
                            {
                              profile_id: group.id,
                              model: model.id,
                              effort: (active ? choice.effort : preferred) as ModelChoice['effort'],
                            },
                            levels,
                          );
                        }}
                      >
                        {highlight === `${group.id}:${model.id}` && (
                          <motion.span
                            aria-hidden="true"
                            className="model-option-glide"
                            layoutId={highlightId}
                            transition={{ duration: reduced ? 0 : 0.2 }}
                          />
                        )}
                        <span className="model-option-label">{model.id}</span>
                        {active && <Check size={14} />}
                      </button>
                    );
                  })}
                </div>
              ))}
            </div>
            {efforts.length > 0 && choice && (
              <fieldset className="model-efforts" disabled={disabled || pending}>
                <legend>思考强度</legend>
                {efforts.map((effort) => (
                  <label key={effort}>
                    <input
                      type="radio"
                      name="model-effort"
                      value={effort}
                      checked={choice.effort === effort}
                      onChange={() =>
                        void select({ ...choice, effort: effort as ModelChoice['effort'] }, efforts)
                      }
                    />
                    <span>{effortLabels[effort] || effort}</span>
                  </label>
                ))}
              </fieldset>
            )}
            {refreshing && (
              <p className="space-note" role="status">
                正在更新可用模型…
              </p>
            )}
            {error && (
              <p className="model-picker-error" role="status">
                {error}
              </p>
            )}
            <button
              type="button"
              className="text-button"
              onClick={() => {
                setOpen(false);
                onSettings();
              }}
            >
              管理模型连接
            </button>
          </Popover.Content>
        </Popover.Portal>
      </Popover.Root>
      {error && !open && (
        <span role="status" className="model-picker-error">
          {error}
        </span>
      )}
    </div>
  );
}
