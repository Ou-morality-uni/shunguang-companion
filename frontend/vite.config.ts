import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import { fileURLToPath, URL } from 'node:url';
import manifest from './package.json';
import { runtimeAssets } from './runtime-assets';

export default defineConfig({
  plugins: [
    {
      name: 'release-version',
      transformIndexHtml: () => [
        { tag: 'meta', attrs: { name: 'shunguang-version', content: manifest.version }, injectTo: 'head' },
      ],
    },
    react(),
    tailwindcss(),
    runtimeAssets(),
  ],
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          const path = id.replaceAll('\\', '/');
          if (!path.includes('/node_modules/')) return;
          if (path.includes('/@assistant-ui/') || path.includes('/assistant-stream/')) return 'assistant';
          if (/\/(motion|motion-dom|motion-utils|framer-motion)\//.test(path)) return 'motion';
          if (/\/(react|react-dom|scheduler)\//.test(path)) return 'react';
          if (path.includes('/radix-ui/') || path.includes('/@radix-ui/')) return 'radix';
          if (/\/(react-markdown|remark-|rehype-|micromark|mdast-|hast-|unist-|unified|vfile)/.test(path))
            return 'markdown';
        },
      },
    },
  },
  server: { proxy: { '/api': { target: 'http://127.0.0.1:8000', ws: true } } },
});
