// Mini App на Vite 8 + React 19 (DEVELOPMENT_PLAN 0.21a, ADR-0012).
import { fontPreload } from '@sosed/design-tokens/vite';
import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import type { Plugin } from 'vite';
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

/** `_headers` в формате Cloudflare (Workers Static Assets, 0.25d): CSP собранного приложения.
 *  Тот же файл применяет статический сервер e2e — тесты ловят нарушения CSP. */
function cspHeaders(mediaOrigins: readonly string[], storageOrigins: readonly string[]): Plugin {
  return {
    name: 'sosed-csp-headers',
    apply: 'build',
    generateBundle() {
      const csp = contentSecurityPolicy({ dev: false, mediaOrigins, storageOrigins });
      this.emitFile({
        type: 'asset',
        fileName: '_headers',
        source: `/*\n  Content-Security-Policy: ${csp}\n`,
      });
    },
  };
}

/** Стенд (`pnpm stand`: vite preview за туннелем): файлы с хешем в имени не меняются — WebView
 *  берёт их из кэша без запроса, как будет на Cloudflare. index.html перепроверяется. */
function immutableAssets(): Plugin {
  return {
    name: 'sosed-immutable-assets',
    configurePreviewServer(server) {
      server.middlewares.use((req, res, next) => {
        if (req.url?.startsWith('/assets/')) {
          res.setHeader('Cache-Control', 'public, max-age=31536000, immutable');
        }
        next();
      });
    },
  };
}

export default defineConfig(({ mode }) => {
  // .env рядом с конфигом: адрес туннеля для allowedHosts (0.22), CDN медиа, DSN Sentry
  const env = loadEnv(mode, import.meta.dirname, '');
  const mediaOrigins = list(env.VITE_MEDIA_ORIGINS);
  const storageOrigins = list(env.TMA_STORAGE_ORIGINS);
  return {
    plugins: [
      react(),
      tailwindcss(),
      fontPreload(),
      cspHeaders(mediaOrigins, storageOrigins),
      immutableAssets(),
    ],
    define: { __APP_VERSION__: JSON.stringify(pkg.version) },
    // manifest — для бюджета первого экрана (scripts/size.ts)
    build: {
      target: BUILD_TARGET,
      sourcemap: true,
      manifest: true,
      // Шрифты — только файлами: data: URI запрещает CSP font-src 'self'
      assetsInlineLimit: (file: string) => (file.endsWith('.woff2') ? false : undefined),
    },
    server: {
      host: '127.0.0.1',
      port: 5173,
      strictPort: true,
      allowedHosts: list(env.TMA_ALLOWED_HOSTS),
      // Через quick tunnel HMR идёт по wss:443 хоста туннеля (make tunnel пишет TMA_HMR_HOST)
      hmr: env.TMA_HMR_HOST
        ? { host: env.TMA_HMR_HOST, protocol: 'wss', clientPort: 443 }
        : undefined,
      proxy: { '/api': 'http://127.0.0.1:8000' },
      headers: {
        'Content-Security-Policy': contentSecurityPolicy({
          dev: true,
          mediaOrigins,
          storageOrigins,
        }),
      },
    },
    preview: {
      host: '127.0.0.1',
      port: 4173,
      // стенд открывается в Telegram через quick tunnel (scripts/tunnel.py) — его хост
      allowedHosts: list(env.TMA_ALLOWED_HOSTS),
      proxy: { '/api': 'http://127.0.0.1:8000' },
      headers: {
        'Content-Security-Policy': contentSecurityPolicy({
          dev: false,
          mediaOrigins,
          storageOrigins,
        }),
      },
    },
  };
});
