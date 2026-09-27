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
    const shapes: Shape[] = [...svg.matchAll(/<(path|circle|rect)\s+([^>]*?)\/>/g)].map(([, tag, attrs]) => [
      tag as Shape[0],
      Object.fromEntries([...(attrs ?? '').matchAll(/([a-z-]+)="([^"]*)"/g)].map(([, k, v]) => [k, v])),
    ]);
    icons[name] = { fill: note.includes('ic fill'), shapes };
  }
  return icons;
}

export function renderIcons(spec: string): string {
  const icons = parseSpecIcons(spec);
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
