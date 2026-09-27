// Каталоги по локалям и неймспейсам. ru и sr-Cyrl ведутся руками, sr-Latn — `pnpm -F i18n generate`.
// Неймспейсы — по группам экранов; новые добавляются сюда и в NAMESPACES.
// common — общие слова и экраны-заготовки; service — «Сервис» SPEC §6 (S48 правила, S49 системные
// состояния); onboarding — «Вход» SPEC §6 (S01 запуск, S02a–c онбординг).
import ruCommon from './catalogs/ru/common.json' with { type: 'json' };
import ruOnboarding from './catalogs/ru/onboarding.json' with { type: 'json' };
import ruService from './catalogs/ru/service.json' with { type: 'json' };
import srCyrlCommon from './catalogs/sr-Cyrl/common.json' with { type: 'json' };
import srCyrlOnboarding from './catalogs/sr-Cyrl/onboarding.json' with { type: 'json' };
import srCyrlService from './catalogs/sr-Cyrl/service.json' with { type: 'json' };
import srLatnCommon from './catalogs/sr-Latn/common.json' with { type: 'json' };
import srLatnOnboarding from './catalogs/sr-Latn/onboarding.json' with { type: 'json' };
import srLatnService from './catalogs/sr-Latn/service.json' with { type: 'json' };
import type { Locale } from './locale.ts';

export const NAMESPACES = ['common', 'service', 'onboarding'] as const;
export type Namespace = (typeof NAMESPACES)[number];

/** Форма каталогов — по ru: ключи остальных локалей сверяет i18n-check. */
export type Messages = {
  common: typeof ruCommon;
  service: typeof ruService;
  onboarding: typeof ruOnboarding;
};

export const RESOURCES: Record<Locale, Messages> = {
  ru: { common: ruCommon, service: ruService, onboarding: ruOnboarding },
  'sr-Cyrl': { common: srCyrlCommon, service: srCyrlService, onboarding: srCyrlOnboarding },
  'sr-Latn': { common: srLatnCommon, service: srLatnService, onboarding: srLatnOnboarding },
};

/** Вручную ведомые локали — источник для генерации и проверок. */
export const SOURCE_LOCALES = ['ru', 'sr-Cyrl'] as const satisfies readonly Locale[];
