import { defineConfig } from 'vite';
export default defineConfig({ base: './', root: 'frontend', build: { outDir: '../dist', emptyOutDir: true }, server: { host: '127.0.0.1', port: 5173, strictPort: true } });
