// Подмножества шрифтов покрывают сербскую латиницу, кириллицу и типографику макетов — и в CSS, и в самих woff2.
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

import { readFontCss, resolveFontFile } from '../scripts/fontsource.ts';
import { woff2Coverage } from '../scripts/woff2.ts';
import { FONT_FAMILIES, FONT_PRELOAD, parseUnicodeRange } from '../src/fonts.ts';
import { fontFaces } from '../src/render.ts';

const SERBIAN_LATIN = 'ČčĆćĐđŠšŽž';
const CYRILLIC = [...Array(0x44f - 0x410 + 1).keys()]
  .map((i) => String.fromCodePoint(0x410 + i))
  .join('');
const SERBIAN_CYRILLIC = 'ЂђЈјЉљЊњЋћЏџЁё';
const PUNCTUATION = '«»—–…·•\u00A0';
/** Встречаются в текстах макетов: «≈ 1,5 км», «×», «→». */
const MOCKUP_SYMBOLS = '≈×→';

const REQUIRED: Record<string, string> = {
  Onest: SERBIAN_LATIN + CYRILLIC + SERBIAN_CYRILLIC + PUNCTUATION + MOCKUP_SYMBOLS,
  Unbounded: SERBIAN_LATIN + CYRILLIC + SERBIAN_CYRILLIC + PUNCTUATION,
};

const faces = fontFaces(readFontCss);
const coverage = new Map(
  faces.map((f) => [f.file, woff2Coverage(readFileSync(resolveFontFile(f.file)))]),
);
const css = readFileSync(new URL('../src/fonts.generated.css', import.meta.url), 'utf8');

const cases = FONT_FAMILIES.flatMap((font) =>
  font.weights.map((weight) => [font.family, weight] as const),
);

describe('шрифты', () => {
  it('подмножества latin, latin-ext, cyrillic, cyrillic-ext у каждого начертания', () => {
    for (const [family, weight] of cases) {
      const subsets = faces
        .filter((f) => f.family === family && f.weight === weight)
        .map((f) => f.subset);
      expect(subsets).toEqual(
        expect.arrayContaining(['latin', 'latin-ext', 'cyrillic', 'cyrillic-ext']),
      );
    }
  });

  it.each(cases)(
    '%s %i: у каждого символа есть подмножество по unicode-range и глиф в его woff2',
    (family, weight) => {
      const own = faces.filter((f) => f.family === family && f.weight === weight);
      const missing = [...(REQUIRED[family] ?? '')].filter((ch) => {
        const cp = ch.codePointAt(0) ?? 0;
        return !own.some(
          (f) =>
            parseUnicodeRange(f.unicodeRange).some(([a, b]) => cp >= a && cp <= b) &&
            coverage.get(f.file)?.(cp),
        );
      });
      expect(missing).toEqual([]);
    },
  );

  it('только self-host woff2 и font-display: swap', () => {
    expect(css).not.toMatch(/https?:|fonts\.googleapis|fonts\.gstatic/);
    const faceCount = css.match(/@font-face/g)?.length ?? 0;
    expect(faceCount).toBe(faces.length);
    expect(css.match(/font-display: swap;/g)?.length).toBe(faceCount);
    expect(css.match(/format\('woff2'\)/g)?.length).toBe(faceCount);
  });

  it('preload указывает на существующие файлы Onest 400 и 600', () => {
    expect(FONT_PRELOAD).toHaveLength(4);
    for (const file of FONT_PRELOAD) {
      expect(faces.map((f) => f.file)).toContain(file);
      expect(() => resolveFontFile(file)).not.toThrow();
    }
  });

  it('разбор unicode-range', () => {
    expect(parseUnicodeRange('U+0400-045F, U+2116')).toEqual([
      [0x400, 0x45f],
      [0x2116, 0x2116],
    ]);
  });
});
