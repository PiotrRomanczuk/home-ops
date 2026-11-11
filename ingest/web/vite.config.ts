import path from 'node:path';
import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

// Served by the ingest container under /mapa/ (see routes/mapa.ts). `npm run
// dev` proxies /api to an ingest instance — uwh on the LAN by default.
export default defineConfig({
  base: '/mapa/',
  plugins: [react(), tailwindcss()],
  resolve: { alias: { '@': path.resolve(import.meta.dirname, './src') } },
  // elk.bundled (~1.5 MB) is its own lazy chunk on purpose.
  build: { outDir: '../public/mapa', emptyOutDir: true, chunkSizeWarningLimit: 1600 },
  server: {
    proxy: { '/api': { target: process.env.INGEST_ORIGIN ?? 'http://192.168.1.75:64421', changeOrigin: true } },
  },
  test: { include: ['src/**/*.test.ts'] },
});
