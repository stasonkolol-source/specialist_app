// Каталоги по локалям и неймспейсам. ru и sr-Cyrl ведутся руками, sr-Latn — `pnpm -F i18n generate`.
// Неймспейсы — по группам экранов; новые добавляются сюда и в NAMESPACES.
// common — общие слова и экраны-заготовки; service — «Сервис» SPEC §6 (S48 правила, S49 системные
// состояния).
import ruCommon from './catalogs/ru/common.json' with { type: 'json' };
import ruService from './catalogs/ru/service.json' with { type: 'json' };
import srCyrlCommon from './catalogs/sr-Cyrl/common.json' with { type: 'json' };
import srCyrlService from './catalogs/sr-Cyrl/service.json' with { type: 'json' };
import srLatnCommon from './catalogs/sr-Latn/common.json' with { type: 'json' };
import srLatnService from './catalogs/sr-Latn/service.json' with { type: 'json' };
import type { Locale } from './locale.ts';

export const NAMESPACES = ['common', 'service'] as const;
export type Namespace = (typeof NAMESPACES)[number];

/** Форма каталогов — по ru: ключи остальных локалей сверяет i18n-check. */
export type Messages = { common: typeof ruCommon; service: typeof ruService };

export const RESOURCES: Record<Locale, Messages> = {
  ru: { common: ruCommon, service: ruService },
  'sr-Cyrl': { common: srCyrlCommon, service: srCyrlService },
  'sr-Latn': { common: srLatnCommon, service: srLatnService },
};

/** Вручную ведомые локали — источник для генерации и проверок. */
export const SOURCE_LOCALES = ['ru', 'sr-Cyrl'] as const satisfies readonly Locale[];
