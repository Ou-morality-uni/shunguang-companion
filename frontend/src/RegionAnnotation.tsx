import { useRef, useState, type PointerEvent } from 'react';
import { Button } from '@/components/ui/button';
import { AnnotationTarget, useAnnotations, type AnnotationAnchor } from './Annotations';

type Rect = [number, number, number, number];
export function RegionAnnotation({
  src,
  alt,
  anchor,
  onError,
}: {
  src: string;
  alt: string;
  anchor: AnnotationAnchor;
  onError?: () => void;
}) {
  const state = useAnnotations();
  const [selecting, setSelecting] = useState(false);
  const [rect, setRect] = useState<Rect | null>(null);
  const dragging = useRef<{ x: number; y: number; bounds: DOMRect; pointer: number } | null>(null);
  function point(event: PointerEvent<HTMLDivElement>, bounds: DOMRect) {
    return {
      x: Math.max(0, Math.min(1, (event.clientX - bounds.left) / bounds.width)),
      y: Math.max(0, Math.min(1, (event.clientY - bounds.top) / bounds.height)),
    };
  }
  function update(event: PointerEvent<HTMLDivElement>) {
    const start = dragging.current;
    if (!start || start.pointer !== event.pointerId) return;
    const end = point(event, start.bounds);
    const round = (value: number) => Math.round(value * 1000000) / 1000000;
    setRect(
      [
        Math.min(start.x, end.x),
        Math.min(start.y, end.y),
        Math.abs(end.x - start.x),
        Math.abs(end.y - start.y),
      ].map(round) as Rect,
    );
  }
  return (
    <div className="region-annotation">
      <div className="work-actions">
        <Button
          type="button"
          variant="outline"
          disabled={state?.sending}
          aria-pressed={selecting}
          onClick={() => {
            setSelecting(!selecting);
            setRect(null);
          }}
        >
          框选区域
        </Button>
        {rect && rect[2] > 0 && rect[3] > 0 && (
          <>
            <Button
              type="button"
              disabled={state?.sending}
              onClick={() => void state?.begin(async () => ({ ...anchor, rect }))}
            >
              批注选区
            </Button>
            <Button type="button" variant="ghost" onClick={() => setRect(null)}>
              清除选区
            </Button>
          </>
        )}
        {selecting && <span className="space-note">拖动框选；按 Escape 退出。</span>}
      </div>
      <AnnotationTarget
        anchor={anchor}
        prepare={async () => ({ ...anchor, ...(rect && rect[2] > 0 && rect[3] > 0 ? { rect } : {}) })}
        label={anchor.location ?? alt}
      >
        <div
          className={`region-surface ${selecting ? 'selecting' : ''}`}
          tabIndex={selecting ? 0 : -1}
          onKeyDown={(event) => {
            if (event.key === 'Escape') {
              setSelecting(false);
              dragging.current = null;
              setRect(null);
            }
          }}
          onPointerDown={(event) => {
            if (!selecting || event.button !== 0 || state?.sending) return;
            const bounds = event.currentTarget.getBoundingClientRect();
            if (!bounds.width || !bounds.height) return;
            dragging.current = { ...point(event, bounds), bounds, pointer: event.pointerId };
            event.preventDefault();
            event.currentTarget.focus();
            event.currentTarget.setPointerCapture?.(event.pointerId);
          }}
          onPointerMove={update}
          onPointerUp={(event) => {
            if (!dragging.current) return;
            update(event);
            dragging.current = null;
            setSelecting(false);
            if (event.currentTarget.hasPointerCapture?.(event.pointerId))
              event.currentTarget.releasePointerCapture(event.pointerId);
          }}
          onPointerCancel={() => {
            dragging.current = null;
            setRect(null);
            setSelecting(false);
          }}
        >
          <img src={src} alt={alt} draggable={false} onError={onError} />
          {rect && (
            <span
              className="region-selection"
              aria-hidden="true"
              style={{
                left: `${rect[0] * 100}%`,
                top: `${rect[1] * 100}%`,
                width: `${rect[2] * 100}%`,
                height: `${rect[3] * 100}%`,
              }}
            />
          )}
        </div>
      </AnnotationTarget>
    </div>
  );
}
