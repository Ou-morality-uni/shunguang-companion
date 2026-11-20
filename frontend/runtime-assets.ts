import { readdir, readFile } from 'node:fs/promises';
import { resolve, join } from 'node:path';
import type { Plugin } from 'vite';

export function runtimeAssets(): Plugin {
  const entries = new Map<string, string>();
  async function discover() {
    if (entries.size) return;
    async function licenses(folder: string, prefix: string) {
      for (const file of await readdir(folder,{withFileTypes:true})) {
        const path = join(folder,file.name), url = `${prefix}/${file.name}`;
        if (file.isDirectory()) await licenses(path,url); else entries.set(url,path);
      }
    }
    await licenses(resolve('licenses'),'/assets/runtime/licenses');
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
