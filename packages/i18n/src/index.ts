// Переводы и форматтеры (ADR-0013): ru и sr-Cyrl — руками, sr-Latn — транслитерацией, en — v1.
export type { Catalog } from './catalog.ts';
export type { CommonKey, Format } from './format.ts';
export { NBSP, createFormat, formatMessage } from './format.ts';
export type { I18nConfig } from './instance.ts';
export { createI18n, currentLocale, i18nReady } from './instance.ts';
export type { Locale, LocaleSources } from './locale.ts';
export {
  DEFAULT_LOCALE,
  INTL_LOCALE,
  LOCALES,
  LOCALE_LABELS,
  LOCALE_NAMES,
  TIME_ZONE,
  UPCOMING_LOCALES,
  isLocale,
  resolveLocale,
} from './locale.ts';
export { I18nextProvider, Trans, useFormat, useLocale, useTranslation } from './react.ts';
export type { Messages, Namespace } from './resources.ts';
export { NAMESPACES, loadNamespace } from './resources.ts';
export { cyrToLat } from './translit.ts';
