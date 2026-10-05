// Бюджет первого экрана (DEVELOPMENT_PLAN 0.21b): JS и CSS, которые браузер грузит до главной
// (вход, его статические импорты и чанк S03), — не больше 200 KB gzip. Шрифты считаются отдельно:
// woff2 уже сжаты, а грузятся только нужные подмножества. Запуск после сборки: pnpm -F tma size.
import { readFileSync } from 'node:fs';
import { gzipSync } from 'node:zlib';

const BUDGET_KB = 200;
const FIRST_ROUTE = 'src/features/catalog/s03-home/index.ts';

interface Chunk {
  file: string;
  src?: string;
  isEntry?: boolean;
  imports?: string[];
  css?: string[];
}

const dist = new URL('../dist/', import.meta.url);
const manifest = JSON.parse(
  readFileSync(new URL('.vite/manifest.json', dist), 'utf8'),
) as Record<string, Chunk>;

const files = new Set<string>();
const visit = (key: string) => {
  const chunk = manifest[key];
  if (!chunk || files.has(chunk.file)) return;
  files.add(chunk.file);
  for (const css of chunk.css ?? []) files.add(css);
  for (const imported of chunk.imports ?? []) visit(imported);
};

// вход страницы — index.html: Главная тоже вход сборки (vite.config.ts), её считаем ниже
const entry = Object.keys(manifest).find(
  (key) => manifest[key]?.isEntry && key.endsWith('.html'),
);
if (!entry) throw new Error('entry chunk not found: build with build.manifest');
visit(entry);
// маршрут переехал, а бюджет молча перестал его считать — так было после 4.8: пусть упадёт
if (!manifest[FIRST_ROUTE]) throw new Error(`first route ${FIRST_ROUTE} is not in the manifest`);
visit(FIRST_ROUTE);

const rows = [...files].map((file) => {
  const bytes = readFileSync(new URL(file, dist));
  return { file, gzip: gzipSync(bytes, { level: 9 }).length };
});
const totalKb = rows.reduce((sum, row) => sum + row.gzip, 0) / 1024;

for (const row of rows.sort((a, b) => b.gzip - a.gzip)) {
  console.log(`${(row.gzip / 1024).toFixed(1).padStart(7)} KB  ${row.file}`);
}
console.log(`${totalKb.toFixed(1).padStart(7)} KB  first screen (budget ${BUDGET_KB} KB gzip)`);
if (totalKb > BUDGET_KB) {
  console.error(`over budget by ${(totalKb - BUDGET_KB).toFixed(1)} KB`);
  process.exit(1);
}
