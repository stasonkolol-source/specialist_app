// Локали интерфейса MVP (ADR-0013). en — v1: пока не выбирается.

export const LOCALES = ['ru', 'sr-Latn', 'sr-Cyrl'] as const;
export type Locale = (typeof LOCALES)[number];

export const DEFAULT_LOCALE: Locale = 'ru';

/** Часовой пояс дат и «сегодня/вчера» — Сербия, независимо от устройства. */
export const TIME_ZONE = 'Europe/Belgrade';

/** Тег для Intl: регион RS даёт сербские форматы чисел и дат. */
export const INTL_LOCALE: Record<Locale, string> = {
  ru: 'ru-RU',
  'sr-Latn': 'sr-Latn-RS',
  'sr-Cyrl': 'sr-Cyrl-RS',
};

/** Самоназвания для выбора языка (SPEC §5): не переводятся и не транслитерируются. */
export const LOCALE_NAMES: Record<Locale, string> = {
  ru: 'Русский',
  'sr-Latn': 'Srpski (latinica)',
  'sr-Cyrl': 'Српски (ћирилица)',
};

export function isLocale(value: unknown): value is Locale {
  return typeof value === 'string' && (LOCALES as readonly string[]).includes(value);
}

/**
 * Язык из внешнего источника (Telegram, браузер). Любой sr* даёт латиницу: кириллица —
 * только явный выбор пользователя (PRODUCT: латиница — умолчание).
 */
function fromTag(tag: string | null | undefined): Locale | null {
  const primary = tag?.trim().toLowerCase().split(/[-_]/)[0];
  if (primary === 'ru') return 'ru';
  if (primary === 'sr') return 'sr-Latn';
  return null;
}

/** Сохранённый выбор (`ui_locale` из /me): явная sr-Cyrl остаётся кириллицей. */
function fromSaved(value: string | null | undefined): Locale | null {
  if (!value) return null;
  const exact = LOCALES.find((l) => l.toLowerCase() === value.trim().toLowerCase());
  return exact ?? fromTag(value);
}

export interface LocaleSources {
  /** `ui_locale` из /me — выбор пользователя в настройках. */
  saved?: string | null;
  /** `language_code` из initData Telegram. */
  telegram?: string | null;
  /** `navigator.languages`. */
  browser?: readonly string[];
}

/** `ui_locale` из /me → `language_code` Telegram → navigator → ru. */
export function resolveLocale({ saved, telegram, browser = [] }: LocaleSources): Locale {
  return (
    fromSaved(saved) ??
    fromTag(telegram) ??
    browser.map(fromTag).find((l) => l !== null) ??
    DEFAULT_LOCALE
  );
}
