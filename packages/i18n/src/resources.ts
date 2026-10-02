// Каталоги по локалям и неймспейсам. ru и sr-Cyrl ведутся руками; sr-Latn — транслитерация sr-Cyrl
// при старте: та же функция, что у `pnpm -F i18n generate`, а файлы sr-Latn в каталогах — для
// ревью и i18n-check. Так третья копия текстов не попадает в первый экран (бюджет 200 KB gzip).
// Неймспейсы — по группам экранов; новые добавляются сюда и в NAMESPACES.
// common — общие слова и экраны-заготовки; service — «Сервис» SPEC §6 (S48 правила, S49 системные
// состояния); onboarding — «Вход» SPEC §6 (S01 запуск, S02a–c онбординг); specialist — «Кабинет
// специалиста» SPEC §6 (S32a–c «Стать специалистом», вход в кабинет на S31); catalog — «Каталог»
// SPEC §6 (S04 категории, S05 выдача, S06 фильтры).
import ruCatalog from './catalogs/ru/catalog.json' with { type: 'json' };
import ruCommon from './catalogs/ru/common.json' with { type: 'json' };
import ruOnboarding from './catalogs/ru/onboarding.json' with { type: 'json' };
import ruService from './catalogs/ru/service.json' with { type: 'json' };
import ruSpecialist from './catalogs/ru/specialist.json' with { type: 'json' };
import srCyrlCatalog from './catalogs/sr-Cyrl/catalog.json' with { type: 'json' };
import srCyrlCommon from './catalogs/sr-Cyrl/common.json' with { type: 'json' };
import srCyrlOnboarding from './catalogs/sr-Cyrl/onboarding.json' with { type: 'json' };
import srCyrlService from './catalogs/sr-Cyrl/service.json' with { type: 'json' };
import srCyrlSpecialist from './catalogs/sr-Cyrl/specialist.json' with { type: 'json' };
import type { Catalog } from './catalog.ts';
import { transliterateCatalog } from './catalog.ts';
import type { Locale } from './locale.ts';

export const NAMESPACES = ['common', 'service', 'onboarding', 'specialist', 'catalog'] as const;
export type Namespace = (typeof NAMESPACES)[number];

/** Форма каталогов — по ru: ключи остальных локалей сверяет i18n-check. */
export type Messages = {
  common: typeof ruCommon;
  service: typeof ruService;
  onboarding: typeof ruOnboarding;
  specialist: typeof ruSpecialist;
  catalog: typeof ruCatalog;
};

function latin<T extends Catalog>(catalog: T): T {
  return transliterateCatalog(catalog) as T;
}

export const RESOURCES: Record<Locale, Messages> = {
  ru: {
    common: ruCommon,
    service: ruService,
    onboarding: ruOnboarding,
    specialist: ruSpecialist,
    catalog: ruCatalog,
  },
  'sr-Cyrl': {
    common: srCyrlCommon,
    service: srCyrlService,
    onboarding: srCyrlOnboarding,
    specialist: srCyrlSpecialist,
    catalog: srCyrlCatalog,
  },
  'sr-Latn': {
    common: latin(srCyrlCommon),
    service: latin(srCyrlService),
    onboarding: latin(srCyrlOnboarding),
    specialist: latin(srCyrlSpecialist),
    catalog: latin(srCyrlCatalog),
  },
};

/** Вручную ведомые локали — источник для генерации и проверок. */
export const SOURCE_LOCALES = ['ru', 'sr-Cyrl'] as const satisfies readonly Locale[];
