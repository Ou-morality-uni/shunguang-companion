import { createWorker, type Worker } from 'tesseract.js';

export type OcrLine = { text: string; confidence: number; rect: [number, number, number, number] };

function abortable<T>(operation: Promise<T>, signal: AbortSignal): Promise<T> {
  return new Promise((resolve, reject) => {
    const stop = () => reject(new DOMException('已取消文字识别', 'AbortError'));
    if (signal.aborted) {
      stop();
      return;
    }
    signal.addEventListener('abort', stop, { once: true });
    operation.then(resolve, reject).finally(() => signal.removeEventListener('abort', stop));
  });
}
const progressNames: Record<string, string> = {
  'loading tesseract core': '载入本机识别引擎',
  'initializing tesseract': '准备识别引擎',
  'loading language traineddata': '载入中英文字典',
  'initializing api': '准备识别',
  'recognizing text': '识别页面文字',
};

export async function recognizePage(
  src: string,
  cancellation: AbortSignal,
  progress: (value: string) => void,
  rotation = 0,
): Promise<OcrLine[]> {
  const signal = AbortSignal.any([cancellation, AbortSignal.timeout(120_000)]);
  let worker: Worker | undefined;
  const stop = () => {
    void worker?.terminate();
  };
  signal.addEventListener('abort', stop, { once: true });
  try {
    const response = await fetch(src, { signal });
    if (!response.ok) throw new Error('无法读取要识别的页面。');
    const image = await createImageBitmap(await response.blob());
    try {
      if (image.width * image.height > 12_000_000) throw new Error('图片过大，请先缩小后识别。');
      const canvas = document.createElement('canvas');
      canvas.width = rotation % 180 ? image.height : image.width;
      canvas.height = rotation % 180 ? image.width : image.height;
      const context = canvas.getContext('2d');
      if (!context) throw new Error('浏览器无法创建图像画布。');
      context.translate(canvas.width / 2, canvas.height / 2);
      context.rotate((rotation * Math.PI) / 180);
      context.drawImage(image, -image.width / 2, -image.height / 2);
      const root = `${location.origin}/assets/runtime/ocr`;
      let failInitialization!: (reason: Error) => void;
      const initializationError = new Promise<Worker>((_, reject) => {
        failInitialization = reject;
      });
      const initialization = createWorker('chi_sim+eng', 1, {
        workerPath: `${root}/worker.min.js`,
        langPath: `${root}/lang`,
        corePath: `${root}/core`,
        workerBlobURL: false,
        logger: (message) =>
          progress(
            `${progressNames[message.status] ?? '正在识别'} ${Math.round((message.progress ?? 0) * 100)}%`,
          ),
        errorHandler: (message) => failInitialization(new Error(String(message))),
      });
      void initialization.then(
        (ready) => {
          if (signal.aborted) void ready.terminate();
        },
        () => {},
      );
      worker = await abortable(Promise.race([initialization, initializationError]), signal);
      if (signal.aborted) throw new DOMException('Aborted', 'AbortError');
      const { data } = await abortable(worker.recognize(canvas, {}, { blocks: true }), signal);
      if (signal.aborted) throw new DOMException('Aborted', 'AbortError');
      return (data.blocks ?? [])
        .flatMap((block) =>
          block.paragraphs.flatMap((paragraph) =>
            paragraph.lines.flatMap((line) =>
              line.words.map((line) => ({
                text: line.text.trim(),
                confidence: line.confidence,
                rect: [
                  line.bbox.x0 / canvas.width,
                  line.bbox.y0 / canvas.height,
                  (line.bbox.x1 - line.bbox.x0) / canvas.width,
                  (line.bbox.y1 - line.bbox.y0) / canvas.height,
                ] as [number, number, number, number],
              })),
            ),
          ),
        )
        .filter((line) => line.text);
    } finally {
      image.close();
    }
  } finally {
    signal.removeEventListener('abort', stop);
    await worker?.terminate();
  }
}
