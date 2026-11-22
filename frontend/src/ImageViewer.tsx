import { useEffect, useRef, useState } from 'react';

export function ImageViewer({ src, name }: { src: string; name: string }) {
  const frame = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState([0, 0]);
  const [natural, setNatural] = useState([0, 0]);
  const [zoom, setZoom] = useState<number | null>(null);
  const [failed, setFailed] = useState(false);
  const points = useRef(new Map<number, { x: number; y: number }>());
  const fit = natural[0] && size[0] ? Math.min(size[0] / natural[0], size[1] / natural[1]) : 1;
  const scale = zoom ?? fit;
  const bounded = (value: number) => Math.max(0.02, Math.min(16, value));
  useEffect(() => {
    const node = frame.current;
    if (!node) return;
    const resize = () => setSize([node.clientWidth, node.clientHeight]);
    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(node);
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    const node = frame.current;
    const wheel = (event: WheelEvent) => {
      event.preventDefault();
      setZoom((value) => bounded((value ?? fit) * Math.exp(-event.deltaY * 0.002)));
    };
    node?.addEventListener('wheel', wheel, { passive: false });
    return () => node?.removeEventListener('wheel', wheel);
  }, [fit]);
  return (
    <>
      <div
        className="drawer-grip"
        aria-hidden="true"
        onPointerDown={(e) => e.currentTarget.setPointerCapture(e.pointerId)}
        onPointerMove={(e) => {
          if (!e.currentTarget.hasPointerCapture(e.pointerId)) return;
          const drawer = e.currentTarget.closest('dialog');
          if (drawer) drawer.style.width = Math.max(300, window.innerWidth - e.clientX) + 'px';
        }}
      />
      <div
        ref={frame}
        className="image-viewport"
        tabIndex={0}
        aria-label="图片预览，滚轮或双指缩放"
        onPointerDown={(e) => {
          e.currentTarget.setPointerCapture(e.pointerId);
          points.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
        }}
        onLostPointerCapture={(e) => points.current.delete(e.pointerId)}
        onPointerMove={(e) => {
          const old = points.current.get(e.pointerId);
          if (!old) return;
          const peer = [...points.current.entries()].find(([id]) => id !== e.pointerId)?.[1];
          if (peer) {
            const previous = Math.hypot(old.x - peer.x, old.y - peer.y);
            if (previous > 0)
              setZoom(bounded((scale * Math.hypot(e.clientX - peer.x, e.clientY - peer.y)) / previous));
          } else {
            e.currentTarget.scrollBy(old.x - e.clientX, old.y - e.clientY);
          }
          points.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
        }}
      >
        {failed ? (
          <span role="alert">图片无法加载，请关闭后重试。</span>
        ) : (
          <img
            src={src}
            alt={name}
            draggable={false}
            style={{ width: natural[0] ? natural[0] * scale : undefined }}
            onLoad={(e) => setNatural([e.currentTarget.naturalWidth, e.currentTarget.naturalHeight])}
            onError={() => setFailed(true)}
          />
        )}
      </div>
      <footer>
        <label>
          缩放{' '}
          <select
            aria-label="缩放比例"
            value={Math.round(scale * 100)}
            onChange={(e) => setZoom(Number(e.target.value) / 100)}
          >
            {[...new Set([25, 50, 75, 100, 150, 200, 400, Math.round(scale * 100)])]
              .sort((a, b) => a - b)
              .map((n) => (
                <option key={n} value={n}>
                  {n}%
                </option>
              ))}
          </select>
        </label>
        <button type="button" onClick={() => setZoom(null)}>
          适应窗口
        </button>
        <button type="button" onClick={() => setZoom(1)}>
          原始大小
        </button>
      </footer>
    </>
  );
}
