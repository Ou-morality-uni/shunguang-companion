import { readdir, readFile } from 'node:fs/promises';
import { resolve, join } from 'node:path';
import type { Plugin } from 'vite';

// Keep workers, fonts and OCR dictionaries on the same origin; never fall back to a CDN.
export function runtimeAssets(): Plugin {
  const roots = {
    'pdfjs/cmaps': 'pdfjs-dist/cmaps',
    'pdfjs/standard_fonts': 'pdfjs-dist/standard_fonts',
    'pdfjs/wasm': 'pdfjs-dist/wasm',
    'pdfjs/iccs': 'pdfjs-dist/iccs',
    'ocr/core': 'tesseract.js-core',
  };
  const entries = new Map<string, string>();
  async function discover() {
    if (entries.size) return;
    for (const [prefix, folder] of Object.entries(roots)) {
      const root = resolve('node_modules', folder);
      for (const name of await readdir(root))
        if (/\.(bcmap|pfb|ttf|wasm|js|gz|icc)$/.test(name) || name.startsWith('LICENSE'))
          entries.set(`/assets/runtime/${prefix}/${name}`, join(root, name));
    }
    for (const language of ['chi_sim','eng']) entries.set(`/assets/runtime/ocr/lang/${language}.traineddata.gz`, resolve(`node_modules/@tesseract.js-data/${language}/4.0.0_best_int/${language}.traineddata.gz`));
    async function licenses(folder: string, prefix: string) {
      for (const file of await readdir(folder,{withFileTypes:true})) {
        const path = join(folder,file.name), url = `${prefix}/${file.name}`;
        if (file.isDirectory()) await licenses(path,url); else entries.set(url,path);
      }
    }
    await licenses(resolve('licenses'),'/assets/runtime/licenses');
    entries.set('/assets/runtime/ocr/worker.min.js', resolve('node_modules/tesseract.js/dist/worker.min.js'));
  }
  return {
    name: 'local-document-runtime-assets',
    async generateBundle() {
      await discover();
      for (const [url, path] of entries)
        this.emitFile({ type: 'asset', fileName: url.slice(1), source: await readFile(path) });
    },
    async configureServer(server) {
      await discover();
      server.middlewares.use(async (req, res, next) => {
        const path = entries.get((req.url ?? '').split('?')[0]);
        if (!path) return next();
        res.setHeader('Content-Type', path.endsWith('.js') ? 'text/javascript' : path.endsWith('.wasm') ? 'application/wasm' : 'application/octet-stream');
        res.end(await readFile(path));
      });
    },
  };
}
