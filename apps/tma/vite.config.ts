// Mini App на Vite 8 + React 19 (DEVELOPMENT_PLAN 0.21a, ADR-0012).
import { fontPreload } from '@sosed/design-tokens/vite';
import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import type { HtmlTagDescriptor, Plugin } from 'vite';
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

/** Чанки и шрифты с хэшем в имени не меняются никогда: повторный запуск берёт их из кэша. */
const IMMUTABLE = 'public, max-age=31536000, immutable';

/** `_headers` в формате Cloudflare (Workers Static Assets, 0.25d): CSP собранного приложения и
 *  кэш (ADR-0012): `/assets/*` с хэшем — навсегда, HTML — с проверкой на каждый запуск, иначе
 *  новый деплой ссылался бы на старые чанки. Тот же файл применяет статический сервер e2e —
 *  тесты ловят нарушения CSP. */
function cspHeaders(mediaOrigins: readonly string[], storageOrigins: readonly string[]): Plugin {
  return {
    name: 'sosed-csp-headers',
    apply: 'build',
    generateBundle() {
      const csp = contentSecurityPolicy({ dev: false, mediaOrigins, storageOrigins });
      const rules: [string, string][] = [
        ['/*', `Content-Security-Policy: ${csp}`],
        ['/assets/*', `Cache-Control: ${IMMUTABLE}`],
        ['/', 'Cache-Control: no-cache'],
        ['/index.html', 'Cache-Control: no-cache'],
      ];
      this.emitFile({
        type: 'asset',
        fileName: '_headers',
        source: rules.map(([path, header]) => `${path}\n  ${header}\n`).join(''),
      });
    },
  };
}

/** Ранние подключения и загрузки первого экрана в index.html: preconnect к CDN медиа (фото
 *  специалистов на Главной) и modulepreload чанка Главной S03 с его зависимостями — браузер качает
 *  их вместе со входом, а не после того, как вход выполнится и начнёт маршрут. */
function firstScreenHints(mediaOrigins: readonly string[]): Plugin {
  let base = '/';
  return {
    name: 'sosed-first-screen-hints',
    apply: 'build',
    configResolved(config) {
      base = config.base;
    },
    transformIndexHtml: {
      order: 'post',
      handler(_html, ctx) {
        const tags: HtmlTagDescriptor[] = mediaOrigins.map((origin) => ({
          tag: 'link',
          attrs: { rel: 'preconnect', href: origin },
          injectTo: 'head',
        }));
        const bundle = ctx.bundle ?? {};
        const chunks = new Map(
          Object.values(bundle).flatMap((chunk) =>
            chunk.type === 'chunk' ? [[chunk.fileName, chunk]] : [],
          ),
        );
        const home = [...chunks.values()].find((chunk) =>
          chunk.facadeModuleId?.endsWith(FIRST_ROUTE),
        );
        const files = new Set<string>();
        const visit = (fileName: string) => {
          const chunk = chunks.get(fileName);
          if (!chunk || chunk.isEntry || files.has(fileName)) return;
          files.add(fileName);
          for (const imported of chunk.imports) visit(imported);
        };
        if (home) visit(home.fileName);
        for (const file of files) {
          tags.push({
            tag: 'link',
            attrs: { rel: 'modulepreload', crossorigin: '', href: `${base}${file}` },
            injectTo: 'head',
          });
        }
        return tags;
      },
    },
  };
}

/** Экран Главной S03 — тот же, что считает бюджет первого экрана (scripts/size.ts). */
const FIRST_ROUTE = 'src/features/catalog/s03-home/index.ts';

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
      firstScreenHints(mediaOrigins),
    ],
    define: { __APP_VERSION__: JSON.stringify(pkg.version) },
    // manifest — для бюджета первого экрана (scripts/size.ts)
    build: {
      target: BUILD_TARGET,
      sourcemap: true,
      manifest: true,
      // Шрифты — только файлами: data: URI запрещает CSP font-src 'self'
      assetsInlineLimit: (file: string) => (file.endsWith('.woff2') ? false : undefined),
      // Всё, что вход импортирует статически, — одним чанком: иначе rolldown выносит модули, общие
      // с ленивыми чанками (i18next, SDK Telegram, хелперы рантайма), в мелкие отдельные. Первый
      // экран — тот же код, но меньше запросов и лучше сжатие. Без рекурсии по зависимостям: иначе
      // в чанк входа попадало и то, что только реэкспортируют пакеты-«бочки» (загрузка медиа,
      // сроки заявок), — оно нужно лишь ленивым экранам. Вход ничего не импортирует из других
      // чанков (scripts/size.ts считает его целиком), поэтому круговых зависимостей с ним нет
      rolldownOptions: {
        output: {
          codeSplitting: {
            groups: [{ name: 'app', tags: ['$initial'], includeDependenciesRecursively: false }],
          },
        },
      },
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
