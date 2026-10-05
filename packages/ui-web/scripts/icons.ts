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

/** Иконки разделов и услуг каталога (backend/seeds/catalog/taxonomy.yaml), которых нет ни в SPEC §3,
 *  ни на артбордах: без них экран показывал запасную grid — «Бьюти» как «Все услуги» (UXM-6).
 *  Источник тот же, что у §3, — Lucide (lucide-static 0.263.0, ISC), контуры как есть; polyline и
 *  line — тем же путём через path. «bolt» (электрика) — молния zap из §3. */
const FROM_CATALOG: Record<string, { fill: boolean; shapes: Shape[] }> = {
  sparkles: {
    fill: false,
    shapes: [
      [
        'path',
        {
          d: 'm12 3-1.912 5.813a2 2 0 0 1-1.275 1.275L3 12l5.813 1.912a2 2 0 0 1 1.275 1.275L12 21l1.912-5.813a2 2 0 0 1 1.275-1.275L21 12l-5.813-1.912a2 2 0 0 1-1.275-1.275L12 3Z',
        },
      ],
      ['path', { d: 'M5 3v4' }],
      ['path', { d: 'M19 17v4' }],
      ['path', { d: 'M3 5h4' }],
      ['path', { d: 'M17 19h4' }],
    ],
  },
  hand: {
    fill: false,
    shapes: [
      ['path', { d: 'M18 11V6a2 2 0 0 0-2-2v0a2 2 0 0 0-2 2v0' }],
      ['path', { d: 'M14 10V4a2 2 0 0 0-2-2v0a2 2 0 0 0-2 2v2' }],
      ['path', { d: 'M10 10.5V6a2 2 0 0 0-2-2v0a2 2 0 0 0-2 2v8' }],
      [
        'path',
        {
          d: 'M18 8a2 2 0 1 1 4 0v6a8 8 0 0 1-8 8h-2c-2.8 0-4.5-.86-5.99-2.34l-3.6-3.6a2 2 0 0 1 2.83-2.82L7 15',
        },
      ],
    ],
  },
  hammer: {
    fill: false,
    shapes: [
      ['path', { d: 'm15 12-8.5 8.5c-.83.83-2.17.83-3 0 0 0 0 0 0 0a2.12 2.12 0 0 1 0-3L12 9' }],
      ['path', { d: 'M17.64 15 22 10.64' }],
      [
        'path',
        {
          d: 'm20.91 11.7-1.25-1.25c-.6-.6-.93-1.4-.93-2.25v-.86L16.01 4.6a5.56 5.56 0 0 0-3.94-1.64H9l.92.82A6.18 6.18 0 0 1 12 8.4v1.56l2 2h2.47l2.26 1.91',
        },
      ],
    ],
  },
  sofa: {
    fill: false,
    shapes: [
      ['path', { d: 'M20 9V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v3' }],
      ['path', { d: 'M2 11v5a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-5a2 2 0 0 0-4 0v2H6v-2a2 2 0 0 0-4 0Z' }],
      ['path', { d: 'M4 18v2' }],
      ['path', { d: 'M20 18v2' }],
      ['path', { d: 'M12 4v9' }],
    ],
  },
  droplet: {
    fill: false,
    shapes: [
      [
        'path',
        {
          d: 'M12 22a7 7 0 0 0 7-7c0-2-1-3.9-3-5.5s-3.5-4-4-6.5c-.5 2.5-2 4.9-4 6.5C6 11.1 5 13 5 15a7 7 0 0 0 7 7z',
        },
      ],
    ],
  },
  box: {
    fill: false,
    shapes: [
      [
        'path',
        {
          d: 'M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z',
        },
      ],
      ['path', { d: 'M3.29 7 12 12 20.71 7' }],
      ['path', { d: 'M12 22V12' }],
    ],
  },
};

export function renderIcons(spec: string): string {
  const fromSpec = parseSpecIcons(spec);
  const icons = { ...fromSpec, ...FROM_ARTBOARDS, ...FROM_CATALOG, bolt: fromSpec.zap };
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
