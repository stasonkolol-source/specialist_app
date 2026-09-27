import { describe, expect, it } from 'vitest';

import { resolveLocale } from './locale.ts';

describe('выбор локали: /me.language → language_code Telegram → navigator → ru', () => {
  it('language_code=sr → sr-Latn (латиница — умолчание)', () => {
    expect(resolveLocale({ telegram: 'sr' })).toBe('sr-Latn');
    expect(resolveLocale({ telegram: 'sr-Cyrl' })).toBe('sr-Latn');
    expect(resolveLocale({ browser: ['sr-RS'] })).toBe('sr-Latn');
  });

  it('явный выбор sr-Cyrl сохраняется', () => {
    expect(resolveLocale({ saved: 'sr-Cyrl', telegram: 'sr' })).toBe('sr-Cyrl');
    expect(resolveLocale({ saved: 'sr-cyrl' })).toBe('sr-Cyrl');
    expect(resolveLocale({ saved: 'sr-Latn', telegram: 'ru' })).toBe('sr-Latn');
  });

  it('сохранённый выбор важнее Telegram, Telegram важнее браузера', () => {
    expect(resolveLocale({ saved: 'ru', telegram: 'sr' })).toBe('ru');
    expect(resolveLocale({ telegram: 'ru', browser: ['sr'] })).toBe('ru');
    expect(resolveLocale({ telegram: 'en', browser: ['de-DE', 'sr-Latn-RS'] })).toBe('sr-Latn');
  });

  it('неподдерживаемые языки (en — v1) → ru', () => {
    expect(resolveLocale({ saved: 'en', telegram: 'en', browser: ['en-US'] })).toBe('ru');
    expect(resolveLocale({})).toBe('ru');
    expect(resolveLocale({ saved: null, telegram: 'ru-RU' })).toBe('ru');
  });
});
