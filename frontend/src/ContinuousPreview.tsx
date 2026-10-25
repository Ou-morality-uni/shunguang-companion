import { useEffect, useRef, useState, type CSSProperties } from 'react';
import { ContextMenu } from 'radix-ui';
import { createPortal } from 'react-dom';
import { Button } from '@/components/ui/button';
import { useAnnotations, type AnnotationAnchor } from './Annotations';
import type { Viewer } from './pdfViewerEngine';
import type { OcrLine } from './localOcr';
import 'pdfjs-dist/web/pdf_viewer.css';
import './continuous-preview.css';

type Region = { page: number; rect: [number, number, number, number] };
function rectWithin(box: DOMRect, page: DOMRect): Region['rect'] | null {
  const x = Math.max(0, box.left - page.left),
    y = Math.max(0, box.top - page.top);
  const width = Math.min(box.right, page.right) - page.left - x;
  const height = Math.min(box.bottom, page.bottom) - page.top - y;
  return width > 0 && height > 0
    ? [x / page.width, y / page.height, width / page.width, height / page.height]
    : null;
}

export function ContinuousPreview({
  url,
  imageUrl,
  anchor,
  image = false,
}: {
  url: string;
  imageUrl: (page: number) => string;
  anchor: AnnotationAnchor;
  image?: boolean;
}) {
  const host = useRef<HTMLDivElement>(null),
    container = useRef<HTMLDivElement>(null);
  const viewer = useRef<Viewer | null>(null);
  const annotations = useAnnotations();
  const [page, setPage] = useState(1),
    [total, setTotal] = useState(0);
  const [captured, setCaptured] = useState(false);
  const [error, setError] = useState(''),
    [commentMode, setCommentMode] = useState(false);
  const [highlight, setHighlight] = useState<CSSProperties | null>(null);
  const target = useRef<AnnotationAnchor | null>(null);
  const [ocr, setOcr] = useState<Record<number, OcrLine[]>>({});
  const [ocrTarget, setOcrTarget] = useState<HTMLElement | null>(null);
  const [recognizing, setRecognizing] = useState(false),
    [progress, setProgress] = useState('');
  const recognition = useRef<AbortController | null>(null);
  useEffect(() => {
    const abort = new AbortController();
    if (!image && container.current)
      void import('./pdfViewerEngine')
        .then(({ createPdfViewer }) =>
          createPdfViewer(
            container.current!,
            url,
            (current, count) => {
              setPage(current);
              setTotal(count);
            },
            abort.signal,
          ),
        )
        .then((value) => {
          if (!abort.signal.aborted) viewer.current = value;
        })
        .catch((failure: Error) => {
          if (!abort.signal.aborted)
            setError(`页面预览暂不可用：${failure.message}。Office 文件请检查 LibreOffice 安装。`);
        });
    return () => {
      abort.abort();
      recognition.current?.abort();
      viewer.current = null;
    };
  }, [url, image]);
  useEffect(() => {
    const update = () =>
      setOcrTarget(
        host.current?.querySelector<HTMLElement>(
          image ? '.image-page' : `.page[data-page-number="${page}"]`,
        ) ?? null,
      );
    update();
    const observer = new MutationObserver(update);
    if (host.current) observer.observe(host.current, { childList: true, subtree: true });
    return () => observer.disconnect();
  }, [page, image]);
  function pageOf(element: Element | null) {
    return element?.closest<HTMLElement>('.page,.image-page') ?? null;
  }
  function sourceRect(rect: Region['rect'] | null): Region['rect'] | null {
    if (!rect) return null;
    const [x, y, w, h] = rect;
    switch (viewer.current?.pagesRotation ?? 0) {
      case 90:
        return [y, Math.max(0, 1 - x - w), h, w];
      case 180:
        return [Math.max(0, 1 - x - w), Math.max(0, 1 - y - h), w, h];
      case 270:
        return [Math.max(0, 1 - y - h), x, h, w];
      default:
        return rect;
    }
  }
  function makeTarget(element: HTMLElement, quote = ''): AnnotationAnchor | null {
    const sourcePage = pageOf(element);
    if (!sourcePage) return null;
    const pageNumber = Number(sourcePage.dataset.pageNumber || 1);
    const rect = sourceRect(rectWithin(element.getBoundingClientRect(), sourcePage.getBoundingClientRect()));
    return {
      ...anchor,
      target_id: image ? 'image' : `page:${pageNumber}`,
      location: image ? '图片' : `第 ${pageNumber} 页`,
      quote,
      regions: rect ? [{ page: pageNumber, rect }] : [],
      text_origin: element.closest('.ocr-text-layer') ? 'ocr' : 'native',
    };
  }
  function capture(event: React.MouseEvent | React.KeyboardEvent) {
    const selection = window.getSelection();
    const selected = selection?.toString().trim();
    if (
      selected &&
      selection?.rangeCount &&
      host.current?.contains(selection.anchorNode) &&
      host.current.contains(selection.focusNode)
    ) {
      const range = selection.getRangeAt(0);
      const regions: Region[] = [];
      for (const sourcePage of host.current.querySelectorAll<HTMLElement>('.page,.image-page')) {
        if (!range.intersectsNode(sourcePage)) continue;
        for (const box of range.getClientRects()) {
          const rect = sourceRect(rectWithin(box, sourcePage.getBoundingClientRect()));
          if (rect && regions.length < 30)
            regions.push({ page: Number(sourcePage.dataset.pageNumber || 1), rect });
        }
      }
      const origin = selection.anchorNode?.parentElement?.closest('.ocr-text-layer') ? 'ocr' : 'native';
      target.current = regions.length
        ? {
            ...anchor,
            target_id: image ? 'image' : `page:${regions[0].page}`,
            quote: selected.slice(0, 20000),
            regions,
            text_origin: origin,
          }
        : null;
    } else {
      const element =
        (event.target as HTMLElement).closest<HTMLElement>(
          '.textLayer span,.ocr-text-layer span,.page img,.image-page img',
        ) ??
        pageOf(event.target as HTMLElement) ??
        host.current?.querySelector<HTMLElement>(
          image ? '.image-page' : `.page[data-page-number="${page}"]`,
        ) ??
        (event.target as HTMLElement);
      target.current = makeTarget(element, element.matches('span') ? (element.textContent ?? '') : '');
    }
    setCaptured(!!target.current);
  }
  function hover(event: React.MouseEvent) {
    if (!commentMode) return;
    const element =
      (event.target as HTMLElement).closest<HTMLElement>(
        '.textLayer span,.ocr-text-layer span,.page img,.image-page img',
      ) ?? pageOf(event.target as Element);
    if (!element || !host.current) {
      setHighlight(null);
      return;
    }
    target.current = makeTarget(element, element.matches('span') ? (element.textContent ?? '') : '');
    const box = element.getBoundingClientRect(),
      bounds = host.current.getBoundingClientRect();
    setHighlight({
      left: box.left - bounds.left,
      top: box.top - bounds.top,
      width: box.width,
      height: box.height,
    });
  }
  function comment() {
    const value = target.current;
    if (value && annotations) {
      void annotations.begin(async () => value);
      setCommentMode(false);
      setHighlight(null);
    }
  }
  async function recognize() {
    if (recognizing) {
      recognition.current?.abort();
      setRecognizing(false);
      setProgress('已取消本次识别');
      return;
    }
    const current = page;
    const abort = new AbortController();
    recognition.current = abort;
    setRecognizing(true);
    setProgress('正在启动本机文字识别…');
    try {
      const { recognizePage } = await import('./localOcr');
      const lines = await recognizePage(
        imageUrl(current),
        abort.signal,
        (message) => {
          if (!abort.signal.aborted) setProgress(message);
        },
        viewer.current?.pagesRotation ?? 0,
      );
      if (!abort.signal.aborted) {
        setOcr((value) => ({ ...value, [current]: lines }));
        const uncertain = lines.filter((line) => line.confidence < 60).length;
        setProgress(
          lines.length
            ? `识别完成，可选中文字添加批注；${uncertain ? `${uncertain} 处置信度较低，` : ''}OCR 内容请与原图核对。`
            : '未识别出文字，可以对整页或图片添加批注。',
        );
      }
    } catch (failure) {
      if (!abort.signal.aborted) setProgress(`文字识别失败：${(failure as Error).message}`);
    } finally {
      if (recognition.current === abort) setRecognizing(false);
    }
  }
  return (
    <div className="continuous-preview">
      <div className="document-toolbar">
        {!image && (
          <>
            <Button
              type="button"
              variant="outline"
              aria-label="缩小文档"
              onClick={() => {
                if (viewer.current)
                  viewer.current.currentScale = Math.max(0.3, viewer.current.currentScale / 1.15);
              }}
            >
              −
            </Button>
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                if (viewer.current) viewer.current.currentScaleValue = 'page-width';
              }}
            >
              适合宽度
            </Button>
            <Button
              type="button"
              variant="outline"
              aria-label="放大文档"
              onClick={() => {
                if (viewer.current)
                  viewer.current.currentScale = Math.min(4, viewer.current.currentScale * 1.15);
              }}
            >
              ＋
            </Button>
            <Button
              type="button"
              variant="outline"
              disabled={recognizing}
              onClick={() => {
                if (viewer.current) {
                  viewer.current.pagesRotation = (viewer.current.pagesRotation + 90) % 360;
                  setOcr({});
                  setCommentMode(false);
                  setHighlight(null);
                  setProgress('');
                }
              }}
            >
              旋转
            </Button>
            <span aria-live="polite">{total ? `${page} / ${total} 页` : '载入页面…'}</span>
          </>
        )}
        <Button type="button" variant="outline" onClick={() => void recognize()}>
          {recognizing ? '取消识别' : '识别文字'}
        </Button>
        {commentMode && (
          <Button
            type="button"
            onClick={() => {
              setCommentMode(false);
              setHighlight(null);
            }}
          >
            退出评论模式
          </Button>
        )}
      </div>
      {progress && (
        <p className="space-note" role="status">
          {progress}
        </p>
      )}
      {error && <p role="status">{error}</p>}
      <ContextMenu.Root>
        <ContextMenu.Trigger asChild disabled={!annotations}>
          <div
            ref={host}
            className={`document-surface ${commentMode ? 'comment-mode' : ''}`}
            onContextMenuCapture={capture}
            onMouseMove={hover}
            onMouseLeave={() => setHighlight(null)}
            onClick={() => {
              if (commentMode) comment();
            }}
            onKeyDownCapture={(event) => {
              if (event.key === 'ContextMenu' || (event.shiftKey && event.key === 'F10')) capture(event);
            }}
          >
            {image ? (
              <div className="image-page" data-page-number="1">
                <img src={url} alt={anchor.name ?? '图片预览'} />
              </div>
            ) : (
              <div ref={container} className="document-scroll" tabIndex={0} aria-label="完整文档连续预览">
                <div className="pdfViewer" />
              </div>
            )}
            {highlight && <div className="comment-highlight" style={highlight} />}
            {ocrTarget &&
              ocr[page] &&
              createPortal(
                <div className="ocr-text-layer">
                  {ocr[page].map((line, index) => (
                    <span
                      key={index}
                      title={`OCR 置信度 ${Math.round(line.confidence)}%`}
                      style={{
                        left: `${line.rect[0] * 100}%`,
                        top: `${line.rect[1] * 100}%`,
                        width: `${line.rect[2] * 100}%`,
                        height: `${line.rect[3] * 100}%`,
                        fontSize: `${Math.max(10, line.rect[3] * ocrTarget.clientHeight * 0.8)}px`,
                      }}
                    >
                      {line.text}
                    </span>
                  ))}
                </div>,
                ocrTarget,
              )}
          </div>
        </ContextMenu.Trigger>
        <ContextMenu.Portal>
          <ContextMenu.Content className="annotation-menu" aria-label="文档批注操作">
            <ContextMenu.Item disabled={!captured || annotations?.sending} onSelect={comment}>
              添加批注
            </ContextMenu.Item>
            <ContextMenu.Item onSelect={() => setCommentMode(true)}>进入评论模式</ContextMenu.Item>
          </ContextMenu.Content>
        </ContextMenu.Portal>
      </ContextMenu.Root>
      <p className="space-note">
        滚动阅读完整文档；选中文字后右键添加批注。评论模式识别文字行和图像，无法可靠分块时定位整页。
      </p>
    </div>
  );
}
