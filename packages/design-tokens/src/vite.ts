// Vite-плагин: <link rel="preload"> для шрифтов первого экрана (FONT_PRELOAD). Имена файлов с хэшем
// известны только после сборки, поэтому ссылки ставятся в transformIndexHtml — после скрипта входа
// и стилей: шрифты с font-display: swap не должны обгонять JS и CSS первого экрана.
import type { HtmlTagDescriptor, Plugin } from 'vite';

import { FONT_PRELOAD } from './fonts.ts';

const basename = (path: string) => path.split('/').at(-1) ?? path;
const WANTED = new Set(FONT_PRELOAD.map(basename));

export function fontPreload(): Plugin {
  let base = '/';
  return {
    name: 'sosed-font-preload',
    apply: 'build',
    configResolved(config) {
      base = config.base;
    },
    transformIndexHtml: {
      order: 'post',
      handler(_html, ctx) {
        const tags: HtmlTagDescriptor[] = [];
        for (const chunk of Object.values(ctx.bundle ?? {})) {
          if (chunk.type !== 'asset') continue;
          const original = chunk.originalFileNames.map(basename);
          if (!original.some((name) => WANTED.has(name))) continue;
          tags.push({
            tag: 'link',
            attrs: {
              rel: 'preload',
              as: 'font',
              type: 'font/woff2',
              crossorigin: '',
              href: `${base}${chunk.fileName}`,
            },
            injectTo: 'head',
          });
        }
        return tags;
      },
    },
  };
}
