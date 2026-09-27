// Операции над каталогами переводов: транслитерация sr-Cyrl → sr-Latn и проверки для make i18n-check.
import { IntlMessageFormat } from 'intl-messageformat';

import { cyrToLat } from './translit.ts';

export interface Catalog {
  [key: string]: string | Catalog;
}

/** sr-Latn — транслитерация sr-Cyrl; синтаксис ICU (имена аргументов, plural/select) — латиница и не меняется. */
export function transliterateCatalog(catalog: Catalog): Catalog {
  return Object.fromEntries(
    Object.entries(catalog).map(([key, value]) => [
      key,
      typeof value === 'string' ? cyrToLat(value) : transliterateCatalog(value),
    ]),
  );
}

/** `{ a: { b: 'x' } }` → `{ 'a.b': 'x' }`. */
export function flattenCatalog(catalog: Catalog, prefix = ''): Record<string, string> {
  return Object.fromEntries(
    Object.entries(catalog).flatMap(([key, value]) =>
      typeof value === 'string'
        ? [[`${prefix}${key}`, value]]
        : Object.entries(flattenCatalog(value, `${prefix}${key}.`)),
    ),
  );
}

interface AstNode {
  type: number;
  value?: unknown;
  options?: Record<string, { value: AstNode[] }>;
  children?: AstNode[];
}

// Типы узлов @formatjs/icu-messageformat-parser: 1 argument, 2 number, 3 date, 4 time, 5 select, 6 plural, 8 tag
const NAMED = new Set([1, 2, 3, 4, 5, 6]);

function collect(nodes: AstNode[], names: Set<string>): void {
  for (const node of nodes) {
    if (NAMED.has(node.type) && typeof node.value === 'string') names.add(node.value);
    for (const option of Object.values(node.options ?? {})) collect(option.value, names);
    if (node.children) collect(node.children, names);
  }
}

/** Имена аргументов ICU-сообщения; бросает при синтаксической ошибке. */
export function messageArguments(message: string, locale: string): string[] {
  const names = new Set<string>();
  collect(new IntlMessageFormat(message, locale).getAst() as AstNode[], names);
  return [...names].sort();
}

/** Буквы русского алфавита, которых нет в сербской кириллице: опечатка раскладки в sr-Cyrl. */
export const NON_SERBIAN_CYRILLIC = /[ЁЙЩЪЫЬЭЮЯёйщъыьэюя]/;
export const ANY_CYRILLIC = /[\u0400-\u04FF]/;
