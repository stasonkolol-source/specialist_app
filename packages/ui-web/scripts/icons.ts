// Иконки из design/SPEC.md §3 → src/icon/icons.generated.ts. С --check только сверяет.
import { readFileSync, writeFileSync } from 'node:fs';

type Shape = [tag: 'path' | 'circle' | 'rect', attrs: Record<string, string>];

export function parseSpecIcons(spec: string): Record<string, { fill: boolean; shapes: Shape[] }> {
  const section = spec.split('## 3. Иконки')[1]?.split('\n## ')[0] ?? '';
  const icons: Record<string, { fill: boolean; shapes: Shape[] }> = {};
  for (const line of section.split('\n')) {
    const row = /^\| ([a-z0-9-]+)(?: \(([^)]*)\))? \| `(<.+>)` \|$/.exec(line.trim());
    if (!row) continue;
    const [, name = '', note = '', svg = ''] = row;
    const shapes: Shape[] = [...svg.matchAll(/<(path|circle|rect)\s+([^>]*?)\/>/g)].map(
      ([, tag, attrs]) => [
        tag as Shape[0],
        Object.fromEntries(
          [...(attrs ?? '').matchAll(/([a-z-]+)="([^"]*)"/g)].map(([, k, v]) => [k, v]),
        ),
      ],
    );
    icons[name] = { fill: note.includes('ic fill'), shapes };
  }
  return icons;
}

/** Есть на артбордах, но нет в таблице SPEC §3 (сверено сканом design/project). */
const FROM_ARTBOARDS: Record<string, { fill: boolean; shapes: Shape[] }> = {
  // S08, S10: видео в портфолио (.ph.play)
  play: { fill: true, shapes: [['path', { d: 'M8 5v14l11-7z' }]] },
  // D03, S58: раздел «Вещи»
  bag: {
    fill: false,
    shapes: [
      ['path', { d: 'M5 8h14l-1 12H6z' }],
      ['path', { d: 'M9 8V6a3 3 0 0 1 6 0v2' }],
    ],
  },
};

export function renderIcons(spec: string): string {
  const icons = { ...parseSpecIcons(spec), ...FROM_ARTBOARDS };
  return [
    '// Сгенерировано scripts/icons.ts из design/SPEC.md §3 — не править руками',
    `export const ICONS = ${JSON.stringify(icons, null, 2)} as const;`,
    '',
    'export type IconName = keyof typeof ICONS;',
    '',
  ].join('\n');
}

const root = `${import.meta.dirname}/../`;
export const SPEC_PATH = `${root}../../design/SPEC.md`;
export const OUT_PATH = `${root}src/icon/icons.generated.ts`;

if (import.meta.url === `file://${process.argv[1]}`) {
  const content = renderIcons(readFileSync(SPEC_PATH, 'utf8'));
  if (process.argv.includes('--check')) {
    if (readFileSync(OUT_PATH, 'utf8') !== content) {
      console.error('icons.generated.ts устарел: pnpm -F ui-web icons');
      process.exit(1);
    }
  } else {
    writeFileSync(OUT_PATH, content);
    console.log(`записан: ${OUT_PATH}`);
  }
}
