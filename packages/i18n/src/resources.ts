// Каталоги по локалям и неймспейсам. ru и sr-Cyrl ведутся руками, sr-Latn — `pnpm -F i18n generate`.
// Неймспейсы — по группам экранов; новые добавляются сюда и в NAMESPACES.
import ruCommon from './catalogs/ru/common.json' with { type: 'json' };
import srCyrlCommon from './catalogs/sr-Cyrl/common.json' with { type: 'json' };
import srLatnCommon from './catalogs/sr-Latn/common.json' with { type: 'json' };
import type { Locale } from './locale.ts';

export const NAMESPACES = ['common'] as const;
export type Namespace = (typeof NAMESPACES)[number];

/** Форма каталогов — по ru: ключи остальных локалей сверяет i18n-check. */
export type Messages = { common: typeof ruCommon };

export const RESOURCES: Record<Locale, Messages> = {
  ru: { common: ruCommon },
  'sr-Cyrl': { common: srCyrlCommon },
  'sr-Latn': { common: srLatnCommon },
};

/** Вручную ведомые локали — источник для генерации и проверок. */
export const SOURCE_LOCALES = ['ru', 'sr-Cyrl'] as const satisfies readonly Locale[];
