// Шрифты self-host из @fontsource: только нужные начертания и подмножества, font-display: swap.
// url — относительный путь в node_modules этого пакета: Tailwind встраивает CSS в пакет-потребитель и
// переносит относительные url, а голый '@fontsource/…' оттуда не находится (pnpm). Google Fonts не нужен.

export interface FontFamily {
  family: string;
  pkg: string;
  weights: number[];
  subsets: string[];
}

const BASE_SUBSETS = ['cyrillic-ext', 'cyrillic', 'latin-ext', 'latin'];

export const FONT_FAMILIES: readonly FontFamily[] = [
  // math — ради «≈» и «→» из текстов макетов («≈ 1,5 км»); качается, только если символ есть на экране
  {
    family: 'Onest',
    pkg: '@fontsource/onest',
    weights: [400, 500, 600, 700],
    subsets: [...BASE_SUBSETS, 'math'],
  },
  { family: 'Unbounded', pkg: '@fontsource/unbounded', weights: [500, 600], subsets: BASE_SUBSETS },
];

/** Первый экран (S01, S03): заголовок Unbounded 600 («Соседи», «Найдём мастера рядом») и текст
 *  Onest 400 и 600 — кириллица; латиница — только 400 («Telegram», цифры, «…»). Латиница 600 на
 *  первом экране не встречается: качается, когда понадобится. Ссылки ставит плагин vite.ts. */
export const FONT_PRELOAD: readonly string[] = [
  '@fontsource/unbounded/files/unbounded-cyrillic-600-normal.woff2',
  '@fontsource/onest/files/onest-cyrillic-400-normal.woff2',
  '@fontsource/onest/files/onest-latin-400-normal.woff2',
  '@fontsource/onest/files/onest-cyrillic-600-normal.woff2',
];

export interface FontFace {
  family: string;
  weight: number;
  subset: string;
  file: string;
  unicodeRange: string;
}

const FACE_RE = /\/\* ([a-z0-9-]+) \*\/\s*@font-face\s*\{([^}]*)\}/g;

/** Разбирает CSS начертания @fontsource (`<pkg>/<weight>.css`) и оставляет нужные подмножества. */
export function parseFontsourceCss(font: FontFamily, weight: number, css: string): FontFace[] {
  const prefix = font.family.toLowerCase();
  const faces: FontFace[] = [];
  for (const [, id = '', body = ''] of css.matchAll(FACE_RE)) {
    const subset = id.slice(prefix.length + 1, -`-${weight}-normal`.length);
    if (!font.subsets.includes(subset)) continue;
    const range = /unicode-range:\s*([^;]+);/.exec(body)?.[1];
    if (!range) throw new Error(`Нет unicode-range у ${id}`);
    faces.push({
      family: font.family,
      weight,
      subset,
      file: `${font.pkg}/files/${id}.woff2`,
      unicodeRange: range.trim(),
    });
  }
  const missing = font.subsets.filter((s) => !faces.some((f) => f.subset === s));
  if (missing.length > 0)
    throw new Error(`${font.family} ${weight}: нет подмножеств ${missing.join(', ')}`);
  return faces;
}

export function renderFontsCss(faces: FontFace[]): string {
  const rules = faces.map((f) =>
    [
      `/* ${f.family} ${f.weight} ${f.subset} */`,
      '@font-face {',
      `  font-family: '${f.family}';`,
      '  font-style: normal;',
      '  font-display: swap;',
      `  font-weight: ${f.weight};`,
      `  src: url('../node_modules/${f.file}') format('woff2');`,
      `  unicode-range: ${f.unicodeRange};`,
      '}',
    ].join('\n'),
  );
  return `/* Сгенерировано scripts/generate.ts из @fontsource — не править руками */\n${rules.join('\n\n')}\n`;
}

/** Диапазоны вида `U+0400-045F,U+2116` → пары [от, до]. */
export function parseUnicodeRange(range: string): [number, number][] {
  return range.split(',').map((part) => {
    const [from = '', to = from] = part.trim().replace(/^U\+/i, '').split('-');
    return [Number.parseInt(from, 16), Number.parseInt(to, 16)];
  });
}
