// PNG-эталоны артбордов design/project → design/reference (спайк 0.19c). Сеть не нужна:
// /_blob/… → design/ui.css, support.js → заглушка, Google Fonts → self-host woff2 из design-tokens.
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';

import { expect, test } from '@playwright/test';

const ROOT = `${import.meta.dirname}/../../../`;
const DESIGN = `${ROOT}design/`;
const ORIGIN = 'http://design.local';
const require = createRequire(`${ROOT}packages/design-tokens/package.json`);

interface Board {
  w: number;
  h: number;
  title: string;
}
const boards = (
  JSON.parse(readFileSync(`${DESIGN}project/canvas.json`, 'utf8')) as {
    boards: Record<string, Board>;
  }
).boards;

/** @font-face из design-tokens с url на локальный маршрут /fonts/<файл>. */
const fontsCss = readFileSync(
  `${ROOT}packages/design-tokens/src/fonts.generated.css`,
  'utf8',
).replace(
  /url\('\.\.\/node_modules\/(@fontsource\/[^']+)'\)/g,
  (_m, spec: string) => `url('${ORIGIN}/fonts/${encodeURIComponent(spec)}')`,
);

function body(path: string): { body: Buffer | string; contentType: string } | null {
  if (path.startsWith('/_blob/'))
    return { body: readFileSync(`${DESIGN}ui.css`), contentType: 'text/css' };
  if (path.endsWith('/support.js')) {
    return {
      body: readFileSync(`${import.meta.dirname}/support-stub.js`),
      contentType: 'text/javascript',
    };
  }
  if (path.startsWith('/fonts/')) {
    const spec = decodeURIComponent(path.slice('/fonts/'.length));
    return { body: readFileSync(require.resolve(spec)), contentType: 'font/woff2' };
  }
  if (path.startsWith('/project/')) {
    return {
      body: readFileSync(`${DESIGN}${path.slice(1)}`),
      contentType: 'text/html; charset=utf-8',
    };
  }
  return null;
}

for (const [file, board] of Object.entries(boards)) {
  test(`${board.title} · ${file}`, async ({ page }) => {
    const external: string[] = [];
    await page.route('**/*', async (route) => {
      const url = new URL(route.request().url());
      if (url.hostname === 'fonts.googleapis.com') {
        await route.fulfill({ body: fontsCss, contentType: 'text/css' });
        return;
      }
      const local = url.origin === ORIGIN ? body(url.pathname) : null;
      if (local) {
        await route.fulfill(local);
        return;
      }
      external.push(url.href);
      await route.abort();
    });
    await page.setViewportSize({ width: board.w, height: board.h });
    await page.goto(`${ORIGIN}/project/${file}`);
    await page.evaluate(() => document.fonts.ready);
    expect(external, 'артборд не должен ходить в сеть').toEqual([]);
    // шрифты грузятся по unicode-range только для реально использованных начертаний: ни одно не должно упасть
    const fonts = await page.evaluate(() => [...document.fonts].map((f) => f.status));
    expect(fonts).toContain('loaded');
    expect(fonts).not.toContain('error');

    // Main — эталон галереи ui-web, отдельно от 71 артборда экранов
    const base = file.replace(/\.dc\.html$/, '');
    const name = `${DESIGN}reference/${file === 'Main.dc.html' ? 'gallery/' : ''}${base}.png`;
    if (file === 'Main.dc.html') {
      await page.screenshot({ path: name, fullPage: true, animations: 'disabled' });
      return;
    }
    const screen = page.locator('.scr').first();
    const box = await screen.boundingBox();
    expect(box?.width).toBe(board.w);
    expect(box?.height).toBe(board.h);
    await screen.screenshot({ path: name, animations: 'disabled' });
  });
}
