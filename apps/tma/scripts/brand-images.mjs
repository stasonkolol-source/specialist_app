// Картинки знака «Соседей» для index.html (8.1) — из шрифтов приложения, без ручной отрисовки:
//   public/favicon.svg           — плашка «С», буква — контуром глифа Unbounded 600 (не текстом:
//                                  у вкладки браузера нет наших шрифтов);
//   public/apple-touch-icon.png  — 180 × 180, плашка во весь квадрат (углы скругляет iOS);
//   public/og-image.png          — 1200 × 630 для превью ссылки: плашка, вордмарк и слоган на #F2F3F5.
// Контур буквы читаем из WOFF @fontsource/unbounded (TrueType: cmap → loca → glyf), PNG рисует
// Chromium Playwright с теми же шрифтами — повторный запуск даёт те же файлы. Только в образе e2e
// (версия Playwright та же, что у @playwright/test), из корня репозитория:
//   docker run --rm --init --ipc=host -v "$PWD:$PWD" -w "$PWD/apps/tma" \
//     mcr.microsoft.com/playwright:v1.63.0-noble node scripts/brand-images.mjs
import { readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { inflateSync } from 'node:zlib';

import { chromium } from '@playwright/test';

const FONTS = '../../packages/design-tokens/node_modules/@fontsource';
const PUBLIC = 'public';
/** Цвета светлой темы (packages/design-tokens): accent, accent-ink, text, text2, bg2. */
const COLOR = {
  accent: '#0B7A5F',
  ink: '#FFFFFF',
  text: '#111418',
  text2: '#5B6270',
  bg2: '#F2F3F5',
};
const NAME = 'Соседи';
const LETTER = NAME.charAt(0);
const SLOGAN = 'Мастера рядом, на вашем языке. Нови-Сад';

const font = (family, file) => readFileSync(join(FONTS, family, 'files', file));

// --- контур глифа из WOFF 1.0 (таблицы сжаты zlib) --------------------------------------------

function woffTables(woff) {
  const tables = new Map();
  const count = woff.readUInt16BE(12);
  for (let i = 0; i < count; i += 1) {
    const entry = 44 + i * 20;
    const tag = woff.toString('latin1', entry, entry + 4);
    const offset = woff.readUInt32BE(entry + 4);
    const compressed = woff.readUInt32BE(entry + 8);
    const length = woff.readUInt32BE(entry + 12);
    const data = woff.subarray(offset, offset + compressed);
    tables.set(tag, compressed < length ? inflateSync(data) : data);
  }
  return tables;
}

/** Номер глифа символа: cmap формата 4 (Unicode BMP). */
function glyphIndex(cmap, code) {
  const count = cmap.readUInt16BE(2);
  for (let i = 0; i < count; i += 1) {
    const offset = cmap.readUInt32BE(4 + i * 8 + 4);
    if (cmap.readUInt16BE(offset) !== 4) continue;
    const segments = cmap.readUInt16BE(offset + 6) / 2;
    const ends = offset + 14;
    const starts = ends + segments * 2 + 2;
    const deltas = starts + segments * 2;
    const ranges = deltas + segments * 2;
    for (let s = 0; s < segments; s += 1) {
      const end = cmap.readUInt16BE(ends + s * 2);
      const start = cmap.readUInt16BE(starts + s * 2);
      if (code < start || code > end) continue;
      const delta = cmap.readInt16BE(deltas + s * 2);
      const range = cmap.readUInt16BE(ranges + s * 2);
      if (range === 0) return (code + delta) & 0xffff;
      const glyph = cmap.readUInt16BE(ranges + s * 2 + range + (code - start) * 2);
      return glyph === 0 ? 0 : (glyph + delta) & 0xffff;
    }
  }
  throw new Error(`нет символа U+${code.toString(16)} в cmap`);
}

/** Контуры простого глифа TrueType: точки { x, y, on } по контурам; составной — по компонентам
 *  со сдвигом (масштаба у букв Unbounded нет). */
function glyphContours(tables, index) {
  const head = tables.get('head');
  const long = head.readInt16BE(50) === 1;
  const loca = tables.get('loca');
  const at = (i) => (long ? loca.readUInt32BE(i * 4) : loca.readUInt16BE(i * 2) * 2);
  const glyf = tables.get('glyf').subarray(at(index), at(index + 1));
  const contours = glyf.readInt16BE(0);
  if (contours < 0) {
    const result = [];
    let p = 10;
    for (;;) {
      const flags = glyf.readUInt16BE(p);
      const component = glyf.readUInt16BE(p + 2);
      const words = flags & 0x1;
      const dx = words ? glyf.readInt16BE(p + 4) : glyf.readInt8(p + 4);
      const dy = words ? glyf.readInt16BE(p + 6) : glyf.readInt8(p + 5);
      p += words ? 8 : 6;
      if (flags & 0x8 || flags & 0x40 || flags & 0x80) throw new Error('масштаб компонента');
      for (const contour of glyphContours(tables, component)) {
        result.push(contour.map((point) => ({ ...point, x: point.x + dx, y: point.y + dy })));
      }
      if (!(flags & 0x20)) return result;
    }
  }
  const ends = Array.from({ length: contours }, (_, i) => glyf.readUInt16BE(10 + i * 2));
  const total = (ends.at(-1) ?? -1) + 1;
  let p = 10 + contours * 2;
  p += 2 + glyf.readUInt16BE(p);
  const flags = [];
  while (flags.length < total) {
    const flag = glyf[p++];
    flags.push(flag);
    if (flag & 0x8) for (let n = glyf[p++]; n > 0; n -= 1) flags.push(flag);
  }
  const coords = (short, same) => {
    let value = 0;
    return flags.map((flag) => {
      if (flag & short) value += flag & same ? glyf[p++] : -glyf[p++];
      else if (!(flag & same)) {
        value += glyf.readInt16BE(p);
        p += 2;
      }
      return value;
    });
  };
  const xs = coords(0x2, 0x10);
  const ys = coords(0x4, 0x20);
  const points = flags.map((flag, i) => ({ x: xs[i], y: ys[i], on: (flag & 0x1) === 1 }));
  return ends.map((end, i) => points.slice(i === 0 ? 0 : ends[i - 1] + 1, end + 1));
}

/** SVG path по контурам: квадратичные кривые, между двумя off-curve — точка посередине. */
function svgPath(contours, map) {
  const fmt = (n) => Number(n.toFixed(2)).toString();
  const xy = (point) => {
    const [x, y] = map(point.x, point.y);
    return `${fmt(x)} ${fmt(y)}`;
  };
  const mid = (a, b) => ({ x: (a.x + b.x) / 2, y: (a.y + b.y) / 2, on: true });
  return contours
    .map((contour) => {
      const start = contour.findIndex((point) => point.on);
      const first = start >= 0 ? contour[start] : mid(contour[0], contour[1]);
      const ring = start >= 0 ? [...contour.slice(start + 1), ...contour.slice(0, start)] : contour;
      let d = `M${xy(first)}`;
      let control = null;
      for (const point of [...ring, first]) {
        if (point.on) {
          d += control ? `Q${xy(control)} ${xy(point)}` : `L${xy(point)}`;
          control = null;
        } else if (control) {
          const between = mid(control, point);
          d += `Q${xy(control)} ${xy(between)}`;
          control = point;
        } else {
          control = point;
        }
      }
      return `${d}Z`;
    })
    .join('');
}

/** Буква знака в квадрате `size` с высотой глифа `height`: по центру рамки глифа. */
function letterPath(size, height) {
  const tables = woffTables(font('unbounded', 'unbounded-cyrillic-600-normal.woff'));
  const contours = glyphContours(tables, glyphIndex(tables.get('cmap'), LETTER.codePointAt(0)));
  const points = contours.flat();
  const minX = Math.min(...points.map((p) => p.x));
  const maxX = Math.max(...points.map((p) => p.x));
  const minY = Math.min(...points.map((p) => p.y));
  const maxY = Math.max(...points.map((p) => p.y));
  const scale = height / (maxY - minY);
  const cx = (minX + maxX) / 2;
  const cy = (minY + maxY) / 2;
  return svgPath(contours, (x, y) => [size / 2 + (x - cx) * scale, size / 2 - (y - cy) * scale]);
}

// --- файлы ------------------------------------------------------------------------------------

/** Плашка знака: квадрат `size` со скруглением `radius` и буквой высотой `height`. */
const plateSvg = (size, radius, height) =>
  `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${size} ${size}">` +
  `<rect width="${size}" height="${size}" rx="${radius}" fill="${COLOR.accent}"/>` +
  `<path d="${letterPath(size, height)}" fill="${COLOR.ink}"/></svg>`;

// Пропорции — как у плашки шапки (24 × 24, радиус 7) и S01 (72, радиус 20, буква 36 px)
writeFileSync(join(PUBLIC, 'favicon.svg'), `${plateSvg(32, 9, 13)}\n`);

/** Подмножества @fontsource: кириллица и латиница (в ней — запятая, точка и дефис слогана). */
const RANGES = { cyrillic: 'U+0400-045F', latin: 'U+0000-00FF' };
const face = (family, weight, subset) => {
  const file = `${family.toLowerCase()}-${subset}-${weight}-normal.woff2`;
  const data = font(family.toLowerCase(), file).toString('base64');
  return `@font-face{font-family:'${family}';font-weight:${weight};unicode-range:${RANGES[subset]};src:url(data:font/woff2;base64,${data}) format('woff2')}`;
};
const fonts = ['cyrillic', 'latin']
  .flatMap((subset) => [face('Unbounded', 600, subset), face('Onest', 500, subset)])
  .join('');

const touchIcon = `<!doctype html><meta charset="utf-8"><style>
html,body{margin:0}svg{display:block;width:180px;height:180px}</style>${plateSvg(180, 0, 68)}`;

const ogImage = `<!doctype html><meta charset="utf-8"><style>${fonts}
html,body{margin:0}
body{width:1200px;height:630px;display:flex;flex-direction:column;align-items:center;
justify-content:center;gap:28px;background:${COLOR.bg2};color:${COLOR.text}}
svg{display:block;width:152px;height:152px}
h1{margin:0;font:600 96px/112px Unbounded,sans-serif;letter-spacing:-0.01em}
p{margin:0;font:500 40px/52px Onest,sans-serif;color:${COLOR.text2}}
</style>${plateSvg(152, 42, 58)}<h1>${NAME}</h1><p>${SLOGAN}</p>`;

const browser = await chromium.launch();
try {
  const page = await browser.newPage({ deviceScaleFactor: 1 });
  for (const [file, html, width, height] of [
    ['apple-touch-icon.png', touchIcon, 180, 180],
    ['og-image.png', ogImage, 1200, 630],
  ]) {
    await page.setViewportSize({ width, height });
    await page.setContent(html);
    await page.evaluate(() => document.fonts.ready);
    await page.screenshot({ path: join(PUBLIC, file), clip: { x: 0, y: 0, width, height } });
  }
} finally {
  await browser.close();
}
console.log('brand-images: favicon.svg, apple-touch-icon.png, og-image.png');
