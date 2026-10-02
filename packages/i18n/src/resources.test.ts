// sr-Latn в приложении считается из sr-Cyrl при загрузке — и совпадает с файлами `pnpm -F i18n
// generate`, которые видят ревью и i18n-check. Сербский — отдельным чанком, русский — сразу.
import { readFileSync } from 'node:fs';

import { describe, expect, it } from 'vitest';

import { EAGER, NAMESPACES, loadNamespace } from './resources.ts';

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
  it('has Russian whole and only the common namespace of Serbian', () => {
    expect(Object.keys(EAGER.ru)).toEqual([...NAMESPACES]);
    expect(Object.keys(EAGER['sr-Cyrl'])).toEqual(['common']);
    expect(EAGER['sr-Latn'].common).toEqual(generated('common'));
  });
});
