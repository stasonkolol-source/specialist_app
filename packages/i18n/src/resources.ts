// Каталоги по локалям и неймспейсам. ru и sr-Cyrl ведутся руками; sr-Latn — транслитерация sr-Cyrl
// при загрузке: та же функция, что у `pnpm -F i18n generate`, а файлы sr-Latn в каталогах — для
// ревью и i18n-check. В первом экране (бюджет 200 KB gzip) — только русский целиком (язык по
// умолчанию и запасной) и общий неймспейс сербского: его читают форматтеры. Остальной сербский —
// отдельным чанком (serbian.ts): приложение дожидается его до первого кадра на сербском и при
// смене языка (instance.ts).
// Неймспейсы — по группам экранов; новые добавляются сюда, в NAMESPACES и в serbian.ts.
// common — общие слова и экраны-заготовки; service — «Сервис» SPEC §6 (S48 правила, S49 системные
// состояния); onboarding — «Вход» SPEC §6 (S01 запуск, S02a–c онбординг); specialist — «Кабинет
// специалиста» SPEC §6 (S32a–c «Стать специалистом», вход в кабинет на S31); catalog — «Каталог»
// SPEC §6 (S04–S06, карточка S08–S11, избранное S12).
import ruCatalog from './catalogs/ru/catalog.json' with { type: 'json' };
import ruCommon from './catalogs/ru/common.json' with { type: 'json' };
import ruOnboarding from './catalogs/ru/onboarding.json' with { type: 'json' };
import ruService from './catalogs/ru/service.json' with { type: 'json' };
import ruSpecialist from './catalogs/ru/specialist.json' with { type: 'json' };
import srCyrlCommon from './catalogs/sr-Cyrl/common.json' with { type: 'json' };
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

export function isNamespace(value: string): value is Namespace {
  return (NAMESPACES as readonly string[]).includes(value);
}

function latin<T extends Catalog>(catalog: T): T {
  return transliterateCatalog(catalog) as T;
}

const RU: Messages = {
  common: ruCommon,
  service: ruService,
  onboarding: ruOnboarding,
  specialist: ruSpecialist,
  catalog: ruCatalog,
};

/** Что есть сразу, без загрузки: русский целиком и общий неймспейс сербского. */
export const EAGER: Record<Locale, Partial<Messages>> = {
  ru: RU,
  'sr-Cyrl': { common: srCyrlCommon },
  'sr-Latn': { common: latin(srCyrlCommon) },
};

/** Общий неймспейс локали — для форматтеров, без экземпляра i18next. */
export function commonOf(locale: Locale): Messages['common'] {
  return EAGER[locale].common ?? RU.common;
}

let serbian: Promise<Messages> | null = null;

function loadSerbian(): Promise<Messages> {
  serbian ??= import('./serbian.ts').then((module) => module.SR_CYRL);
  return serbian;
}

/** Каталог неймспейса: ru — сразу, sr-Cyrl — из чанка, sr-Latn — транслитерацией sr-Cyrl. */
export async function loadNamespace(locale: Locale, namespace: Namespace): Promise<Catalog> {
  if (locale === 'ru') return RU[namespace];
  const cyrillic = (await loadSerbian())[namespace];
  return locale === 'sr-Cyrl' ? cyrillic : latin(cyrillic);
}

/** Вручную ведомые локали — источник для генерации и проверок. */
export const SOURCE_LOCALES = ['ru', 'sr-Cyrl'] as const satisfies readonly Locale[];
