// Mini App на Vite 8 + React 19 (DEVELOPMENT_PLAN 0.21a, ADR-0012).
import { fontPreload } from '@sosed/design-tokens/vite';
import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { defineConfig, loadEnv } from 'vite';

import pkg from './package.json' with { type: 'json' };
import { contentSecurityPolicy } from './src/app/csp.ts';

/** Q4 не решён владельцем — умолчание плана: iOS 15+ (Safari 15), Android WebView на Chromium. */
export const BUILD_TARGET = ['safari15', 'chrome100', 'firefox100'];

const list = (value: string | undefined): string[] =>
  (value ?? '')
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean);

export default defineConfig(({ mode }) => {
  // .env рядом с конфигом: адрес туннеля для allowedHosts (0.22), CDN медиа, DSN Sentry
  const env = loadEnv(mode, import.meta.dirname, '');
  const mediaOrigins = list(env.VITE_MEDIA_ORIGINS);
  return {
    plugins: [react(), tailwindcss(), fontPreload()],
    define: { __APP_VERSION__: JSON.stringify(pkg.version) },
    build: { target: BUILD_TARGET, sourcemap: true },
    server: {
      host: '127.0.0.1',
      port: 5173,
      strictPort: true,
      allowedHosts: list(env.TMA_ALLOWED_HOSTS),
      proxy: { '/api': 'http://127.0.0.1:8000' },
      headers: { 'Content-Security-Policy': contentSecurityPolicy({ dev: true, mediaOrigins }) },
    },
    preview: {
      host: '127.0.0.1',
      port: 4173,
      proxy: { '/api': 'http://127.0.0.1:8000' },
      headers: { 'Content-Security-Policy': contentSecurityPolicy({ dev: false, mediaOrigins }) },
    },
  };
});
