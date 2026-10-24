import {
  useCallback,
  useContext,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from 'react';
import { createPortal } from 'react-dom';
import { motion, useReducedMotion } from 'motion/react';
import { Maximize2, Minimize2, X } from 'lucide-react';
import { ResourcePreview } from './ResourcePreview';
import { PreviewContext as Context, type Preview, type PreviewResource } from './PreviewContext';

type ResourceTabs = Record<string, { tabs: PreviewResource[]; active: string; visible: boolean }>;
const TABS_KEY = 'shunguang.resource-tabs.v1';

function savedTabs(): ResourceTabs {
  try {
    const raw = sessionStorage.getItem(TABS_KEY);
    if (!raw || raw.length > 200000) return {};
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return {};
    const result: ResourceTabs = {};
    for (const [scope, entry] of Object.entries(parsed).slice(-100)) {
      if (
        ['__proto__', 'constructor', 'prototype'].includes(scope) ||
        scope.length > 180 ||
        !entry ||
        typeof entry !== 'object' ||
        !('tabs' in entry) ||
        !Array.isArray(entry.tabs)
      )
        continue;
      const candidates: unknown[] = entry.tabs;
      const tabs = candidates
        .filter((value: unknown): value is PreviewResource => {
          if (!value || typeof value !== 'object') return false;
          return (
            'kind' in value &&
            ['attachment', 'artifact', 'task', 'history'].includes(String(value.kind)) &&
            'id' in value &&
            typeof value.id === 'string' &&
            value.id.length > 0 &&
            value.id.length <= 100 &&
            'title' in value &&
            typeof value.title === 'string' &&
            value.title.length <= 256
          );
        })
        .slice(-32)
        .map(({ id, kind, title }) => ({ id, kind, title }));
      const active = 'active' in entry && typeof entry.active === 'string' ? entry.active : '';
      if (!tabs.some((item) => `${item.kind}:${item.id}` === active)) continue;
      result[scope] = { tabs, active, visible: 'visible' in entry && entry.visible === true };
    }
    return result;
  } catch {
    return {};
  }
}

export function PreviewWorkspace({
  children,
  resetKey,
  onSettings,
}: {
  children: ReactNode;
  resetKey?: string;
  onSettings?: () => void;
}) {
  const reduced = useReducedMotion();
  const [legacyActive, setLegacyActive] = useState<Preview | null>(null);
  const scope = resetKey ?? 'default';
  const [resources, setResources] = useState<ResourceTabs>(savedTabs);
  useEffect(() => {
    try {
      sessionStorage.setItem(TABS_KEY, JSON.stringify(resources));
    } catch {
      // Storage can be disabled; in-memory tabs remain usable.
    }
  }, [resources]);
  const current = resources[scope];
  const resource = current?.visible
    ? current.tabs.find((item) => `${item.kind}:${item.id}` === current.active)
    : undefined;
  const triggers = useRef<Record<string, HTMLElement | null>>({});
  const active = resource
    ? {
        id: `${resource.kind}:${resource.id}`,
        title: resource.title,
        trigger: triggers.current[`${scope}:${current.active}`] ?? null,
        close: () => {},
      }
    : legacyActive;
  const activeRef = useRef<Preview | null>(null);
  const [host, setHost] = useState<HTMLDivElement | null>(null);
  const [width, setWidth] = useState(46),
    [expanded, setExpanded] = useState(false);
  const [narrow, setNarrow] = useState(
    () => typeof matchMedia !== 'undefined' && matchMedia('(max-width:980px)').matches,
  );
  useEffect(() => {
    if (typeof matchMedia === 'undefined') return;
    const media = matchMedia('(max-width:980px)');
    const change = () => setNarrow(media.matches);
    media.addEventListener('change', change);
    return () => media.removeEventListener('change', change);
  }, []);
  const workspace = useRef<HTMLDivElement>(null);
  const panel = useRef<HTMLElement>(null);
  useEffect(() => {
    activeRef.current?.close();
    activeRef.current = null;
    setLegacyActive(null);
    setExpanded(false);
  }, [resetKey]);
  const open = useCallback((value: Preview) => {
    if (activeRef.current?.id !== value.id) activeRef.current?.close();
    activeRef.current = value;
    setLegacyActive(value);
    setExpanded(false);
    return () => {
      if (activeRef.current?.id === value.id) {
        activeRef.current = null;
        setLegacyActive(null);
      }
    };
  }, []);
  const openResource = useCallback(
    (value: PreviewResource, trigger?: HTMLElement | null) => {
      const key = `${value.kind}:${value.id}`;
      triggers.current[`${scope}:${key}`] = trigger ?? null;
      activeRef.current?.close();
      activeRef.current = null;
      setLegacyActive(null);
      setResources((previous) => {
        const tabs = previous[scope]?.tabs ?? [];
        return {
          ...previous,
          [scope]: {
            tabs: tabs.some((item) => `${item.kind}:${item.id}` === key) ? tabs : [...tabs, value],
            active: key,
            visible: true,
          },
        };
      });
      setExpanded(false);
    },
    [scope],
  );
  function selectResource(key: string) {
    setResources((previous) => ({
      ...previous,
      [scope]: { ...previous[scope], active: key, visible: true },
    }));
  }
  function closeResource(key: string) {
    setResources((previous) => {
      const before = previous[scope];
      const tabs = before.tabs.filter((item) => `${item.kind}:${item.id}` !== key);
      const next = before.active === key ? tabs.at(-1) : null;
      return {
        ...previous,
        [scope]: {
          tabs,
          active: next ? `${next.kind}:${next.id}` : before.active,
          visible: tabs.length > 0 && before.visible,
        },
      };
    });
  }
  const visible = !!active;
  useLayoutEffect(() => {
    if (visible) panel.current?.focus();
  }, [visible, resetKey]);
  function close() {
    if (resource) {
      setResources((previous) => ({ ...previous, [scope]: { ...previous[scope], visible: false } }));
      setExpanded(false);
      if (active?.trigger?.isConnected) active.trigger.focus();
      return;
    }
    const previous = activeRef.current;
    activeRef.current = null;
    setLegacyActive(null);
    setExpanded(false);
    previous?.close();
    if (previous?.trigger?.isConnected) {
      const target = previous.trigger.matches(':disabled')
        ? previous.trigger.closest<HTMLElement>('article')
        : previous.trigger;
      target?.focus();
    }
  }
  const resize = (value: number) => setWidth(Math.max(30, Math.min(68, value)));
  return (
    <Context.Provider value={{ active: active?.id ?? null, host, open, openResource }}>
      <div
        ref={workspace}
        className={`preview-workspace ${active ? 'has-preview' : ''} ${expanded ? 'preview-expanded' : ''}`}
        style={{ '--preview-width': `${width}%` } as CSSProperties}
      >
        <div className="preview-main" inert={(!!active && (expanded || narrow)) || undefined}>
          {children}
        </div>
        {active && (
          <div
            role="separator"
            aria-label="调整预览宽度"
            aria-orientation="vertical"
            aria-valuemin={30}
            aria-valuemax={68}
            aria-valuenow={width}
            tabIndex={0}
            className="preview-divider"
            onKeyDown={(event) => {
              if (['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) {
                event.preventDefault();
                resize(
                  event.key === 'Home'
                    ? 30
                    : event.key === 'End'
                      ? 68
                      : width + (event.key === 'ArrowLeft' ? 5 : -5),
                );
              }
            }}
            onPointerDown={(event) => {
              event.currentTarget.setPointerCapture(event.pointerId);
            }}
            onPointerMove={(event) => {
              if (!event.currentTarget.hasPointerCapture(event.pointerId)) return;
              const bounds = workspace.current?.getBoundingClientRect();
              if (bounds?.width) resize(Math.round(((bounds.right - event.clientX) / bounds.width) * 100));
            }}
            onPointerUp={(event) => {
              if (event.currentTarget.hasPointerCapture(event.pointerId))
                event.currentTarget.releasePointerCapture(event.pointerId);
            }}
          />
        )}
        <aside
          ref={panel}
          hidden={!active}
          tabIndex={-1}
          role="region"
          aria-label="文件预览"
          className="preview-panel"
          onKeyDown={(event) => {
            if (event.key === 'Escape') {
              event.stopPropagation();
              close();
            }
            if (event.key === 'Tab' && (expanded || narrow)) {
              const controls = Array.from(
                event.currentTarget.querySelectorAll<HTMLElement>(
                  'button:not(:disabled), a[href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex="0"]',
                ),
              );
              const first = controls[0],
                last = controls.at(-1);
              if (
                event.shiftKey &&
                (document.activeElement === first || document.activeElement === panel.current)
              ) {
                event.preventDefault();
                last?.focus();
              } else if (
                !event.shiftKey &&
                (document.activeElement === last || document.activeElement === panel.current)
              ) {
                event.preventDefault();
                first?.focus();
              }
            }
          }}
        >
          <header className="preview-heading">
            <div>
              <span className="eyebrow">资料与成果</span>
              <h2>{active?.title}</h2>
            </div>
            <div className="preview-actions">
              <button
                className="icon-button"
                aria-label={expanded ? '还原并排' : '放大预览'}
                onClick={() => setExpanded(!expanded)}
              >
                {expanded ? <Minimize2 size={18} /> : <Maximize2 size={18} />}
              </button>
              <button className="icon-button" aria-label="关闭预览" onClick={close}>
                <X size={19} />
              </button>
            </div>
          </header>
          {resource && (
            <div
              role="tablist"
              aria-label="已打开的资料与成果"
              className="preview-tabs"
              onKeyDown={(event) => {
                if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
                const items = Array.from(
                  event.currentTarget.querySelectorAll<HTMLButtonElement>('[role="tab"]'),
                );
                const index = items.indexOf(event.target as HTMLButtonElement);
                if (index < 0) return;
                event.preventDefault();
                const next =
                  event.key === 'Home'
                    ? 0
                    : event.key === 'End'
                      ? items.length - 1
                      : (index + (event.key === 'ArrowLeft' ? -1 : 1) + items.length) % items.length;
                items[next]?.click();
                items[next]?.focus();
              }}
            >
              {current.tabs.map((item) => {
                const key = `${item.kind}:${item.id}`;
                return (
                  <div key={key} className="preview-tab">
                    <button
                      role="tab"
                      aria-selected={current.active === key}
                      tabIndex={current.active === key ? 0 : -1}
                      onClick={() => selectResource(key)}
                    >
                      {current.active === key && (
                        <motion.span
                          aria-hidden="true"
                          className="selection-glide"
                          layoutId="resource-tab-highlight"
                          transition={{ duration: reduced ? 0 : 0.22 }}
                        />
                      )}
                      {item.title}
                    </button>
                    <button
                      className="icon-button"
                      aria-label={`关闭标签 ${item.title}`}
                      onClick={() => closeResource(key)}
                    >
                      <X size={13} />
                    </button>
                  </div>
                );
              })}
            </div>
          )}
          {resource ? (
            <div className="preview-body">
              <ResourcePreview
                key={`${scope}:${current.active}`}
                resource={resource}
                onSettings={onSettings}
              />
            </div>
          ) : (
            <div ref={setHost} className="preview-body" />
          )}
        </aside>
      </div>
    </Context.Provider>
  );
}

export function FilePreview({
  title,
  onClose,
  returnFocus,
  children,
}: {
  title: string;
  onClose: () => void;
  returnFocus?: HTMLElement | null;
  children: ReactNode;
}) {
  const context = useContext(Context),
    id = useId();
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;
  const open = context?.open;
  useLayoutEffect(
    () =>
      open?.({
        id,
        title,
        close: () => onCloseRef.current(),
        trigger:
          returnFocus ?? (document.activeElement instanceof HTMLElement ? document.activeElement : null),
      }),
    [open, id, title, returnFocus],
  );
  if (!context) return <>{children}</>;
  return context.active === id && context.host ? createPortal(children, context.host) : null;
}

export { useResourcePreview } from './PreviewContext';
