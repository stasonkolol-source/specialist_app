// Сгенерированные файлы актуальны и согласованы между собой.
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

import source from '../tokens.json' with { type: 'json' };
import { readFontCss } from '../scripts/fontsource.ts';
import { renderAll, themeColors } from '../src/render.ts';
import { color, tokens } from '../src/index.ts';

const files = renderAll(source, readFontCss);

describe('сгенерированные файлы', () => {
  it.each(files.map((f) => [f.path, f.content]))(
    '%s актуален (pnpm -F design-tokens generate)',
    (path, content) => {
      expect(readFileSync(new URL(`../${path}`, import.meta.url), 'utf8')).toBe(content);
    },
  );

  it('@theme объявляет утилиту на каждый цвет и радиус', () => {
    const theme = files.find((f) => f.path.endsWith('theme.generated.css'))?.content ?? '';
    for (const name of Object.keys(themeColors(source, 'light'))) {
      expect(theme).toContain(`--color-${name}: var(--${name});`);
    }
    for (const name of Object.keys(source.radius)) {
      expect(theme).toContain(`--radius-${name}: var(--r-${name});`);
    }
    expect(theme).toContain('--font-sans: var(--f-ui);');
  });

  it('TS-экспорт повторяет цвета обеих тем', () => {
    expect(tokens.color.light).toEqual(themeColors(source, 'light'));
    expect(tokens.color.dark).toEqual(themeColors(source, 'dark'));
    // отдельный экспорт цветов — тот же объект: точка сборки Mini App берёт только его
    expect(color).toBe(tokens.color);
  });
});
