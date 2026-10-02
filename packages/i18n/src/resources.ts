// Каталоги по локалям и неймспейсам. ru и sr-Cyrl ведутся руками; sr-Latn — транслитерация sr-Cyrl
// при загрузке: та же функция, что у `pnpm -F i18n generate`, а файлы sr-Latn в каталогах — для
// ревью и i18n-check. В первом экране (бюджет 200 KB gzip) — русские неймспейсы Главной и
// системных состояний (FIRST_SCREEN; русский — язык по умолчанию и запасной) и общий неймспейс
// сербского: его читают форматтеры. Остальной русский — своими маленькими чанками, остальной
// сербский — одним (serbian.ts). До первого кадра приложение ждёт только FIRST_SCREEN своего языка
// (instance.ts); экран с другим неймспейсом ждёт его сам (Suspense), а после первого кадра все
// неймспейсы догружаются в простое.
// Неймспейсы — по группам экранов; новые добавляются сюда, в NAMESPACES и в serbian.ts.
// common — общие слова и экраны-заготовки; service — «Сервис» SPEC §6 (S48 правила, S49 системные
// состояния); onboarding — «Вход» SPEC §6 (S01 запуск, S02a–c онбординг); specialist — «Кабинет
// специалиста» SPEC §6 (S32a–c «Стать специалистом», вход в кабинет на S31); catalog — «Каталог»
// SPEC §6 (S04–S06, карточка S08–S11, избранное S12); jobs — «Заявки» SPEC §6 (создание S20a–d,
// S21; дальше лента, отклики, мои заявки); messages — «Сообщения» SPEC §6 (S29 диалоги, S30 чат).
import ruCatalog from './catalogs/ru/catalog.json' with { type: 'json' };
import ruCommon from './catalogs/ru/common.json' with { type: 'json' };
import type ruJobs from './catalogs/ru/jobs.json';
import type ruMessages from './catalogs/ru/messages.json';
import type ruOnboarding from './catalogs/ru/onboarding.json';
import ruService from './catalogs/ru/service.json' with { type: 'json' };
import type ruSpecialist from './catalogs/ru/specialist.json';
import srCyrlCommon from './catalogs/sr-Cyrl/common.json' with { type: 'json' };
import type { Catalog } from './catalog.ts';
import { transliterateCatalog } from './catalog.ts';
import type { Locale } from './locale.ts';

export const NAMESPACES = [
  'common',
  'service',
  'onboarding',
  'specialist',
  'catalog',
  'jobs',
  'messages',
] as const;
export type Namespace = (typeof NAMESPACES)[number];

/** Неймспейсы до первого кадра: Главная (catalog) и системные состояния (service) — без сети
 *  S49a «Нет соединения» должен показаться, а догрузить каталог будет нельзя. */
export const FIRST_SCREEN = ['common', 'service', 'catalog'] as const satisfies Namespace[];
type FirstScreen = (typeof FIRST_SCREEN)[number];

/** Форма каталогов — по ru: ключи остальных локалей сверяет i18n-check. */
export type Messages = {
  common: typeof ruCommon;
  service: typeof ruService;
  onboarding: typeof ruOnboarding;
  specialist: typeof ruSpecialist;
  catalog: typeof ruCatalog;
  jobs: typeof ruJobs;
  messages: typeof ruMessages;
};

export function isNamespace(value: string): value is Namespace {
  return (NAMESPACES as readonly string[]).includes(value);
}

function latin<T extends Catalog>(catalog: T): T {
  return transliterateCatalog(catalog) as T;
}

const RU: Pick<Messages, FirstScreen> = {
  common: ruCommon,
  service: ruService,
  catalog: ruCatalog,
};

/** Остальной русский — каждый неймспейс своим чанком. */
const RU_LATER: Record<Exclude<Namespace, FirstScreen>, () => Promise<Catalog>> = {
  onboarding: () => import('./catalogs/ru/onboarding.json').then((module) => module.default),
  specialist: () => import('./catalogs/ru/specialist.json').then((module) => module.default),
  jobs: () => import('./catalogs/ru/jobs.json').then((module) => module.default),
  messages: () => import('./catalogs/ru/messages.json').then((module) => module.default),
};

const isFirstScreen = (namespace: Namespace): namespace is FirstScreen =>
  (FIRST_SCREEN as readonly string[]).includes(namespace);

/** Что есть сразу, без загрузки: русский первого экрана и общий неймспейс сербского. */
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

/** Каталог неймспейса: ru — сразу или своим чанком, sr-Cyrl — из сербского чанка, sr-Latn —
 *  транслитерацией sr-Cyrl. */
export async function loadNamespace(locale: Locale, namespace: Namespace): Promise<Catalog> {
  if (locale === 'ru') return isFirstScreen(namespace) ? RU[namespace] : RU_LATER[namespace]();
  const cyrillic = (await loadSerbian())[namespace];
  return locale === 'sr-Cyrl' ? cyrillic : latin(cyrillic);
}

/** Вручную ведомые локали — источник для генерации и проверок. */
export const SOURCE_LOCALES = ['ru', 'sr-Cyrl'] as const satisfies readonly Locale[];
