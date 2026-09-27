// Генерирует src/*.generated.* из tokens.json и @fontsource. С флагом --check только сверяет.
import { readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import source from '../tokens.json' with { type: 'json' };
import { renderAll } from '../src/render.ts';
import { readFontCss } from './fontsource.ts';

const root = fileURLToPath(new URL('..', import.meta.url));
const check = process.argv.includes('--check');
let stale = 0;

for (const file of renderAll(source, readFontCss)) {
  const path = `${root}${file.path}`;
  if (check) {
    let current = '';
    try {
      current = readFileSync(path, 'utf8');
    } catch {
      // файла нет — считаем устаревшим
    }
    if (current !== file.content) {
      stale += 1;
      console.error(`устарел: ${file.path}`);
    }
  } else {
    writeFileSync(path, file.content);
    console.log(`записан: ${file.path}`);
  }
}

if (stale > 0) {
  console.error('Запустите: pnpm -F design-tokens generate');
  process.exit(1);
}
