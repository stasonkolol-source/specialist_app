// Галерея компонентов: отдельный Vite-вход внутри ui-web, не часть apps/tma.
import { fontPreload } from '@sosed/design-tokens/vite';
import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

export default defineConfig({
  root: import.meta.dirname,
  base: './',
  plugins: [react(), tailwindcss(), fontPreload()],
  build: { outDir: '../dist-gallery', emptyOutDir: true },
  server: { port: 5174 },
  preview: { port: 4173 },
});
