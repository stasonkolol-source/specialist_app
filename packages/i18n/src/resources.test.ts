// sr-Latn в приложении считается из sr-Cyrl при старте — и совпадает с файлами `pnpm -F i18n
// generate`, которые видят ревью и i18n-check.
import { readFileSync } from 'node:fs';

import { describe, expect, it } from 'vitest';

import { NAMESPACES, RESOURCES } from './resources.ts';

const generated = (namespace: string): unknown =>
  JSON.parse(
    readFileSync(new URL(`./catalogs/sr-Latn/${namespace}.json`, import.meta.url), 'utf8'),
  );

describe('sr-Latn', () => {
  it.each([...NAMESPACES])('%s совпадает со сгенерированным файлом', (namespace) => {
    expect(RESOURCES['sr-Latn'][namespace]).toEqual(generated(namespace));
  });
});
