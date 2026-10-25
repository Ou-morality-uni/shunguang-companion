import * as pdfjs from 'pdfjs-dist';
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url';
import type { PDFViewer } from 'pdfjs-dist/web/pdf_viewer.mjs';

pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;
const positions = new Map<string, { page: number; scale: string; rotation: number }>();

export async function createPdfViewer(
  container: HTMLDivElement,
  url: string,
  onPage: (page: number, total: number) => void,
  signal: AbortSignal,
) {
  // The official viewer distribution consumes the matching library through this documented global.
  Object.assign(globalThis, { pdfjsLib: pdfjs });
  const { EventBus, PDFViewer, PDFLinkService } = await import('pdfjs-dist/web/pdf_viewer.mjs');
  if (signal.aborted) throw new DOMException('Aborted', 'AbortError');
  const eventBus = new EventBus();
  const linkService = new PDFLinkService({ eventBus });
  const lifetime = new AbortController();
  // PDF.js accepts abortSignal; its generated option declaration currently omits it.
  const viewerOptions = {
    container,
    eventBus,
    linkService,
    annotationMode: 0,
    imagesRightClickMinSize: 1,
    textLayerMode: 1,
    maxCanvasPixels: 8 * 1024 * 1024,
    abortSignal: lifetime.signal,
  };
  const viewer = new PDFViewer(viewerOptions);
  linkService.setViewer(viewer);
  const task = pdfjs.getDocument({
    url,
    cMapUrl: '/assets/runtime/pdfjs/cmaps/',
    cMapPacked: true,
    standardFontDataUrl: '/assets/runtime/pdfjs/standard_fonts/',
    wasmUrl: '/assets/runtime/pdfjs/wasm/',
    iccUrl: '/assets/runtime/pdfjs/iccs/',
    enableXfa: false,
  });
  let lastWidth = container.clientWidth;
  const resize = new ResizeObserver(() => {
    if (!viewer.pdfDocument || container.clientWidth < 1) return;
    if (container.clientWidth !== lastWidth) {
      lastWidth = container.clientWidth;
      const scale = viewer.currentScaleValue;
      if (['auto', 'page-fit', 'page-width', 'page-height'].includes(scale)) viewer.currentScaleValue = scale;
    }
    viewer.update();
  });
  resize.observe(container);
  let closed = false;
  const close = () => {
    if (closed) return;
    closed = true;
    resize.disconnect();
    lifetime.abort();
    signal.removeEventListener('abort', close);
    if (viewer.pdfDocument) {
      positions.delete(url);
      positions.set(url, {
        page: viewer.currentPageNumber,
        scale: viewer.currentScaleValue,
        rotation: viewer.pagesRotation,
      });
      if (positions.size > 40) positions.delete(positions.keys().next().value!);
    }
    viewer.setDocument(null);
    void task.destroy();
  };
  signal.addEventListener('abort', close, { once: true });
  try {
    const document = await task.promise;
    if (signal.aborted) throw new DOMException('Aborted', 'AbortError');
    eventBus.on(
      'pagesinit',
      () => {
        const previous = positions.get(url);
        viewer.pagesRotation = previous?.rotation ?? 0;
        viewer.currentScaleValue = previous?.scale || 'page-width';
        viewer.currentPageNumber = Math.min(previous?.page ?? 1, document.numPages);
        onPage(viewer.currentPageNumber, document.numPages);
      },
      { signal: lifetime.signal },
    );
    eventBus.on(
      'pagechanging',
      ({ pageNumber }: { pageNumber: number }) => onPage(pageNumber, document.numPages),
      { signal: lifetime.signal },
    );
    viewer.setDocument(document);
    linkService.setDocument(document);
    return viewer;
  } catch (error) {
    close();
    throw error;
  }
}

export type Viewer = PDFViewer;
