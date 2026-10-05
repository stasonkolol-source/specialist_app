// sr-Latn в приложении считается из sr-Cyrl при загрузке — и совпадает с файлами `pnpm -F i18n
// generate`, которые видят ревью и i18n-check. Русский первого экрана и общий сербский — сразу,
// остальное — своими чанками по неймспейсу.
import { readFileSync } from 'node:fs';

import { describe, expect, it } from 'vitest';

import { EAGER, FIRST_SCREEN, NAMESPACES, loadNamespace } from './resources.ts';

const generated = (namespace: string): unknown =>
  JSON.parse(
    readFileSync(new URL(`./catalogs/sr-Latn/${namespace}.json`, import.meta.url), 'utf8'),
  );

describe('sr-Latn', () => {
  it.each([...NAMESPACES])('%s совпадает со сгенерированным файлом', async (namespace) => {
    expect(await loadNamespace('sr-Latn', namespace)).toEqual(generated(namespace));
  });
});

describe('first screen', () => {
  it('has Russian of the first screen and only the common namespace of Serbian', () => {
    expect(Object.keys(EAGER.ru).sort()).toEqual([...FIRST_SCREEN].sort());
    expect(Object.keys(EAGER['sr-Cyrl'])).toEqual(['common']);
    expect(EAGER['sr-Latn'].common).toEqual(generated('common'));
  });

  it.each(NAMESPACES.filter((ns) => ns !== 'common'))(
    'Serbian %s comes later from its own file, not with all the others',
    async (namespace) => {
      const file: unknown = JSON.parse(
        readFileSync(new URL(`./catalogs/sr-Cyrl/${namespace}.json`, import.meta.url), 'utf8'),
      );
      expect(await loadNamespace('sr-Cyrl', namespace)).toEqual(file);
    },
  );

  it.each(NAMESPACES.filter((ns) => !(FIRST_SCREEN as readonly string[]).includes(ns)))(
    'Russian %s comes later from its own file',
    async (namespace) => {
      const file: unknown = JSON.parse(
        readFileSync(new URL(`./catalogs/ru/${namespace}.json`, import.meta.url), 'utf8'),
      );
      expect(await loadNamespace('ru', namespace)).toEqual(file);
    },
  );
});
