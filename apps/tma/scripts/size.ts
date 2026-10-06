// Бюджет первого экрана (DEVELOPMENT_PLAN 0.21b): JS и CSS, которые браузер грузит до главной
// (вход, его статические импорты и чанк S03), — не больше 200 KB gzip. Шрифты считаются отдельно:
// woff2 уже сжаты, а грузятся только нужные подмножества. Запуск после сборки: pnpm -F tma size.
// Считаются оба пути, русский и сербский: кроме входа и Главной, Главная ждёт ещё чанк своих текстов
// на языке пользователя (каталог, packages/i18n, resources.ts) — бюджет у обоих один.
import { readFileSync } from 'node:fs';
import { gzipSync } from 'node:zlib';

const BUDGET_KB = 200;
const FIRST_ROUTE = 'src/features/catalog/s03-home/index.ts';
/** Неймспейсы Главной, которых нет во входе: FIRST_SCREEN (packages/i18n) без common — общие
 *  неймспейсы лежат во входе (S01, S49a, форматтеры). sr-Latn — транслитерация того же sr-Cyrl. */
const FIRST_SCREEN_TEXTS = (locale: 'ru' | 'sr-Cyrl') => [
  `../../packages/i18n/src/catalogs/${locale}/catalog.json`,
];

interface Chunk {
  file: string;
  src?: string;
  isEntry?: boolean;
  imports?: string[];
  css?: string[];
}

const dist = new URL('../dist/', import.meta.url);
const manifest = JSON.parse(readFileSync(new URL('.vite/manifest.json', dist), 'utf8')) as Record<
  string,
  Chunk
>;

/** Файлы чанков `keys` с их статическими импортами и CSS. */
function closure(keys: readonly string[]): Set<string> {
  const files = new Set<string>();
  const visit = (key: string) => {
    const chunk = manifest[key];
    if (!chunk || files.has(chunk.file)) return;
    files.add(chunk.file);
    for (const css of chunk.css ?? []) files.add(css);
    for (const imported of chunk.imports ?? []) visit(imported);
  };
  for (const key of keys) {
    // чанк переехал, а бюджет молча перестал его считать — так было после 4.8: пусть упадёт
    if (!manifest[key]) throw new Error(`${key} is not in the manifest`);
    visit(key);
  }
  return files;
}

const gzipKb = (file: string) =>
  gzipSync(readFileSync(new URL(file, dist)), { level: 9 }).length / 1024;

// вход страницы — index.html: Главная тоже вход сборки (vite.config.ts), её считаем вместе с ним
const entry = Object.keys(manifest).find((key) => manifest[key]?.isEntry && key.endsWith('.html'));
if (!entry) throw new Error('entry chunk not found: build with build.manifest');
const russian = closure([entry, FIRST_ROUTE, ...FIRST_SCREEN_TEXTS('ru')]);
const serbian = closure([entry, FIRST_ROUTE, ...FIRST_SCREEN_TEXTS('sr-Cyrl')]);

const all = new Set([...russian, ...serbian]);
const sizes = new Map([...all].map((file) => [file, gzipKb(file)]));
const total = (files: Set<string>) =>
  [...files].reduce((sum, file) => sum + (sizes.get(file) ?? 0), 0);

for (const [file, kb] of [...sizes].sort((a, b) => b[1] - a[1])) {
  const only =
    russian.has(file) && serbian.has(file) ? '' : russian.has(file) ? '  (ru)' : '  (sr)';
  console.log(`${kb.toFixed(1).padStart(7)} KB  ${file}${only}`);
}
let over = false;
for (const [name, files] of [
  ['ru', russian],
  ['sr', serbian],
] as const) {
  const kb = total(files);
  console.log(
    `${kb.toFixed(1).padStart(7)} KB  first screen ${name} (budget ${BUDGET_KB} KB gzip)`,
  );
  if (kb > BUDGET_KB) {
    console.error(`${name}: over budget by ${(kb - BUDGET_KB).toFixed(1)} KB`);
    over = true;
  }
}
if (over) process.exit(1);
