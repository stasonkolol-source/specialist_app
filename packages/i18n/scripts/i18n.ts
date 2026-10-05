// node scripts/i18n.ts generate — sr-Latn из sr-Cyrl; check — актуальность sr-Latn и согласованность каталогов.
import { readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import type { Catalog } from '../src/catalog.ts';
import {
  ANY_CYRILLIC,
  NON_SERBIAN_CYRILLIC,
  NON_SERBIAN_STYLE,
  flattenCatalog,
  messageArguments,
  transliterateCatalog,
} from '../src/catalog.ts';

const dir = fileURLToPath(new URL('../src/catalogs/', import.meta.url));
const read = (locale: string, file: string): Catalog => JSON.parse(readFileSync(`${dir}${locale}/${file}`, 'utf8'));
const files = readdirSync(`${dir}sr-Cyrl`).filter((f) => f.endsWith('.json'));

export function renderSrLatn(file: string): string {
  return `${JSON.stringify(transliterateCatalog(read('sr-Cyrl', file)), null, 2)}\n`;
}

/** Ошибки каталогов: пустой список — всё в порядке. */
export function checkCatalogs(): string[] {
  const errors: string[] = [];
  const ruFiles = readdirSync(`${dir}ru`).filter((f) => f.endsWith('.json'));
  if (ruFiles.join() !== files.join()) errors.push(`неймспейсы ru и sr-Cyrl различаются: ${ruFiles} / ${files}`);
  for (const file of files) {
    let current = '';
    try {
      current = readFileSync(`${dir}sr-Latn/${file}`, 'utf8');
    } catch {
      // файла нет — устарел
    }
    if (current !== renderSrLatn(file)) errors.push(`sr-Latn/${file} устарел: pnpm -F i18n generate`);

    const ru = flattenCatalog(read('ru', file));
    const sr = flattenCatalog(read('sr-Cyrl', file));
    const lat = flattenCatalog(transliterateCatalog(read('sr-Cyrl', file)));
    for (const key of new Set([...Object.keys(ru), ...Object.keys(sr)])) {
      const where = `${file}: ${key}`;
      const ruMsg = ru[key];
      const srMsg = sr[key];
      if (ruMsg === undefined || srMsg === undefined) {
        errors.push(`${where} — нет в ${ruMsg === undefined ? 'ru' : 'sr-Cyrl'}`);
        continue;
      }
      if (NON_SERBIAN_CYRILLIC.test(srMsg)) errors.push(`${where} — в sr-Cyrl русская буква: «${srMsg}»`);
      if (NON_SERBIAN_STYLE.test(srMsg)) errors.push(`${where} — кавычки или «чет» не по глоссарию: «${srMsg}»`);
      if (ANY_CYRILLIC.test(lat[key] ?? '')) errors.push(`${where} — в sr-Latn осталась кириллица`);
      try {
        const args = [messageArguments(ruMsg, 'ru'), messageArguments(srMsg, 'sr-Cyrl')];
        if (args[0]?.join() !== args[1]?.join()) errors.push(`${where} — разные аргументы: ${args[0]} / ${args[1]}`);
      } catch (e) {
        errors.push(`${where} — ошибка ICU: ${(e as Error).message}`);
      }
    }
  }
  return errors;
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const command = process.argv[2];
  if (command === 'generate') {
    for (const file of files) {
      writeFileSync(`${dir}sr-Latn/${file}`, renderSrLatn(file));
      console.log(`записан: sr-Latn/${file}`);
    }
  } else if (command === 'check') {
    const errors = checkCatalogs();
    for (const e of errors) console.error(e);
    if (errors.length > 0) process.exit(1);
    console.log(`i18n: ${files.length} неймспейс(ов), каталоги согласованы, sr-Latn актуален`);
  } else {
    console.error('Использование: node scripts/i18n.ts generate|check');
    process.exit(2);
  }
}
