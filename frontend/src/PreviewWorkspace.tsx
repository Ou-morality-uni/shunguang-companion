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
            ['attachment', 'artifact', 'history'].includes(String(value.kind)) &&
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
      if (!tabs.length) continue;
      const saved = 'active' in entry && typeof entry.active === 'string' ? entry.active : '';
      const active = tabs.some((item) => `${item.kind}:${item.id}` === saved)
        ? saved
        : `${tabs[0].kind}:${tabs[0].id}`;
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
  const divider = useRef<HTMLDivElement>(null);
  const balancedWidth = useRef(46);
  const beforeExpand = useRef(46);
  const scrollPositions = useRef<{ element: HTMLElement; top: number; left: number }[]>([]);
  const restoreScroll = useRef(false);
  const panel = useRef<HTMLElement>(null);
  useEffect(() => {
    activeRef.current?.close();
    activeRef.current = null;
    setLegacyActive(null);
    setExpanded(false);
    scrollPositions.current = [];
  }, [resetKey]);
  const open = useCallback((value: Preview) => {
    if (activeRef.current?.id !== value.id) activeRef.current?.close();
    activeRef.current = value;
    setLegacyActive(value);
    setExpanded(false);
    setWidth((previous) => (previous === 0 ? 46 : previous));
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
      setWidth((previous) => (previous === 0 ? 46 : previous));
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
  const resize = (value: number) => {
    const next = Math.max(0, Math.min(100, value));
    setWidth(next);
  };
  function rememberLayout() {
    if (width === 0 || width === 100) return;
    balancedWidth.current = width;
    scrollPositions.current = Array.from(
      workspace.current?.querySelectorAll<HTMLElement>(
        '.conversation-scroll, .preview-body, .office-sheet-scroll, .document-scroll',
      ) ?? [],
      (element) => ({ element, top: element.scrollTop, left: element.scrollLeft }),
    );
  }
  useLayoutEffect(() => {
    if (!active) return;
    if (restoreScroll.current) {
      for (const { element, top, left } of scrollPositions.current) {
        if (element.isConnected) {
          element.scrollTop = top;
          element.scrollLeft = left;
        }
      }
      restoreScroll.current = false;
    }
    const focused = document.activeElement;
    if (
      (width === 0 && panel.current?.contains(focused)) ||
      (width === 100 && workspace.current?.querySelector('.preview-main')?.contains(focused))
    )
      divider.current?.focus();
  }, [width, active]);
  return (
    <Context.Provider value={{ active: active?.id ?? null, host, open, openResource }}>
      <div
        ref={workspace}
        className={`preview-workspace ${active ? 'has-preview' : ''} ${expanded ? 'preview-expanded' : ''} ${active && width === 0 ? 'preview-file-collapsed' : ''} ${active && width === 100 ? 'preview-chat-collapsed' : ''}`}
        style={{ '--preview-width': `${width}%`, '--preview-ratio': width / 100 } as CSSProperties}
      >
        <div className="preview-main" inert={(!!active && (width === 100 || narrow)) || undefined}>
          {children}
        </div>
        {active && (
          <div
            ref={divider}
            role="separator"
            aria-label="调整预览宽度"
            aria-orientation="vertical"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={width}
            tabIndex={0}
            className="preview-divider"
            onKeyDown={(event) => {
              if (['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) {
                event.preventDefault();
                if (['Home', 'End'].includes(event.key)) rememberLayout();
                resize(
                  event.key === 'Home'
                    ? 0
                    : event.key === 'End'
                      ? 100
                      : width + (event.key === 'ArrowLeft' ? 5 : -5),
                );
              }
            }}
            onPointerDown={(event) => {
              rememberLayout();
              event.currentTarget.setPointerCapture(event.pointerId);
            }}
            onPointerMove={(event) => {
              if (!event.currentTarget.hasPointerCapture(event.pointerId)) return;
              const bounds = workspace.current?.getBoundingClientRect();
              if (bounds?.width) {
                const value = Math.round(((bounds.right - event.clientX) / bounds.width) * 100);
                resize(value <= 2 ? 0 : value >= 98 ? 100 : value);
              }
            }}
            onPointerUp={(event) => {
              if (event.currentTarget.hasPointerCapture(event.pointerId))
                event.currentTarget.releasePointerCapture(event.pointerId);
            }}
          />
        )}
        {active && (width === 0 || width === 100) && (
          <button
            type="button"
            className={`preview-restore ${width === 0 ? 'restore-file' : 'restore-chat'}`}
            onClick={() => {
              restoreScroll.current = true;
              resize(balancedWidth.current);
              divider.current?.focus();
            }}
          >
            {width === 0 ? '展开预览' : '展开聊天'}
          </button>
        )}
        <aside
          ref={panel}
          hidden={!active}
          inert={width === 0 || undefined}
          tabIndex={-1}
          role="region"
          aria-label="文件预览"
          className="preview-panel"
          onKeyDown={(event) => {
            if (event.key === 'Escape') {
              event.stopPropagation();
              close();
            }
            if (event.key === 'Tab' && narrow) {
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
                onClick={() => {
                  if (expanded) {
                    restoreScroll.current = true;
                    resize(beforeExpand.current);
                  } else {
                    rememberLayout();
                    beforeExpand.current = width > 0 && width < 100 ? width : 46;
                    resize(60);
                  }
                  setExpanded(!expanded);
                }}
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
