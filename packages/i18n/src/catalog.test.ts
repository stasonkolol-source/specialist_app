import { describe, expect, it } from 'vitest';

import {
  ANY_CYRILLIC,
  NON_SERBIAN_CYRILLIC,
  flattenCatalog,
  messageArguments,
  transliterateCatalog,
} from './catalog.ts';

describe('каталоги', () => {
  it('sr-Latn — транслитерация всех строк, структура та же', () => {
    const cyr = { a: 'Љубав', b: { c: '{count, plural, one {# дан} other {# дана}}' } };
    expect(transliterateCatalog(cyr)).toEqual({
      a: 'Ljubav',
      b: { c: '{count, plural, one {# dan} other {# dana}}' },
    });
  });

  it('плоские ключи', () => {
    expect(flattenCatalog({ a: { b: 'x', c: { d: 'y' } }, e: 'z' })).toEqual({
      'a.b': 'x',
      'a.c.d': 'y',
      e: 'z',
    });
  });

  it('аргументы ICU, включая вложенные в plural и select', () => {
    expect(messageArguments('{day} в {time}', 'ru')).toEqual(['day', 'time']);
    expect(messageArguments('{n, plural, one {# из {total}} other {#}}', 'ru')).toEqual([
      'n',
      'total',
    ]);
    expect(() => messageArguments('{broken', 'ru')).toThrow();
  });

  it('русская буква в sr-Cyrl и кириллица в sr-Latn ловятся', () => {
    expect(NON_SERBIAN_CYRILLIC.test('Подели ђаче')).toBe(false);
    expect(NON_SERBIAN_CYRILLIC.test('Подели ещё')).toBe(true);
    expect(ANY_CYRILLIC.test('Podeli')).toBe(false);
    expect(ANY_CYRILLIC.test('Podeliы')).toBe(true);
  });
});
