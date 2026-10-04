import { describe, expect, it } from 'vitest';

import golden from '../golden.json' with { type: 'json' };
import { BASE62_ALPHABET, base62ToUuid, uuidToBase62 } from './base62.ts';
import type { StartLink } from './startapp.ts';
import {
  START_PARAM_MAX_LENGTH,
  StartParamError,
  encodeStartParam,
  isValidStartParam,
  parseStartParam,
} from './startapp.ts';

describe('golden-векторы (общие с backend)', () => {
  it('алфавит совпадает', () => {
    expect(golden.alphabet).toBe(BASE62_ALPHABET);
  });

  it.each(golden.uuid)('$uuid ⇄ $base62', ({ uuid, base62 }) => {
    expect(uuidToBase62(uuid)).toBe(base62);
    expect(base62ToUuid(base62)).toBe(uuid);
  });

  it.each(golden.valid)('$param', ({ param, link }) => {
    expect(encodeStartParam(link as StartLink)).toBe(param);
    expect(parseStartParam(param)).toEqual(link);
  });

  it.each(golden.invalid)('«%s» не разбирается', (param) => {
    expect(parseStartParam(param)).toBeNull();
  });
});

describe('base62', () => {
  it('ровно 22 символа для любого UUID', () => {
    for (const uuid of golden.uuid.map((v) => v.uuid)) expect(uuidToBase62(uuid)).toHaveLength(22);
  });

  it('UUID в верхнем регистре кодируется так же и декодируется в нижний', () => {
    const uuid = '0192F5A8-7C3E-7B21-9D4F-3A6B8C1E2F47';
    expect(base62ToUuid(uuidToBase62(uuid))).toBe(uuid.toLowerCase());
  });

  it('не принимает не-UUID и значения больше 2^128 − 1', () => {
    expect(() => uuidToBase62('not-a-uuid')).toThrow(TypeError);
    expect(base62ToUuid('7n42DGM5Tflk9n8mt7Fhc8')).toBeNull();
    expect(base62ToUuid('short')).toBeNull();
  });
});

describe('коды startapp', () => {
  const id = '0192f5a8-7c3e-7b21-9d4f-3a6b8c1e2f47';

  it('лимит 64 символа', () => {
    const maxRef = 'A'.repeat(START_PARAM_MAX_LENGTH - 26);
    expect(encodeStartParam({ type: 'specialist', id, ref: maxRef })).toHaveLength(64);
    expect(() => encodeStartParam({ type: 'specialist', id, ref: `${maxRef}A` })).toThrow(
      StartParamError,
    );
    expect(isValidStartParam('h'.repeat(65))).toBe(false);
  });

  it('`gh` и `h` — разные типы', () => {
    expect(parseStartParam('h')).toEqual({ type: 'home' });
    expect(parseStartParam('gh')).toEqual({ type: 'reserved', code: 'gh' });
    expect(encodeStartParam({ type: 'home' })).toBe('h');
    expect(encodeStartParam({ type: 'reserved', code: 'gh' })).toBe('gh');
  });

  it('суффикс `_r<code>` — только суффикс', () => {
    expect(parseStartParam('h_rAB12CD')).toEqual({ type: 'home', ref: 'AB12CD' });
    expect(parseStartParam('rAB12CD')).toBeNull();
    // у зарезервированного кода значение может начинаться с r: это значение, а не реферал
    expect(parseStartParam('gs_r42')).toEqual({ type: 'reserved', code: 'gs', value: 'r42' });
  });

  it('партнёрские параметры Telegram `_tgr_` не наши', () => {
    expect(isValidStartParam('_tgr_abc')).toBe(false);
    expect(parseStartParam('_tgr_abc')).toBeNull();
  });

  it('недопустимые значения кодирования', () => {
    expect(() => encodeStartParam({ type: 'home', ref: 'A_B' })).toThrow(StartParamError);
    expect(() => encodeStartParam({ type: 'reserved', code: 'gs' })).toThrow(StartParamError);
    expect(() => encodeStartParam({ type: 'reserved', code: 'gh', value: '1' })).toThrow(
      StartParamError,
    );
    expect(() => encodeStartParam({ type: 'reserved', code: 'gc', value: 'a_b' })).toThrow(
      StartParamError,
    );
    expect(() => encodeStartParam({ type: 'mine', section: 'unknown' as 'jobs' })).toThrow(
      StartParamError,
    );
  });

  it('пустое значение и null', () => {
    expect(parseStartParam(null)).toBeNull();
    expect(parseStartParam(undefined)).toBeNull();
  });
});
