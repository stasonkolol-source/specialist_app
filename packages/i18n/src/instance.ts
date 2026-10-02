// Экземпляр i18next с ICU. Создаётся один раз в apps/tma/src/app и передаётся провайдером (ADR-0020 §13).
// Каталоги вне первого экрана грузятся чанками (resources.ts): `i18nReady` — когда на месте тексты
// первого экрана текущего языка, точка сборки ждёт его до первого кадра; `preloadCatalogs` — после
// него, в простое. Экран с ещё не загруженным неймспейсом ждёт его сам (Suspense), смена языка —
// тоже.
import i18next from 'i18next';
import type { BackendModule, i18n as I18n } from 'i18next';
import ICU from 'i18next-icu';
import { initReactI18next } from 'react-i18next';

import type { Locale } from './locale.ts';
import { DEFAULT_LOCALE, LOCALES, isLocale } from './locale.ts';
import type { Messages } from './resources.ts';
import { EAGER, FIRST_SCREEN, NAMESPACES, isNamespace, loadNamespace } from './resources.ts';
import { cyrToLat } from './translit.ts';

declare module 'i18next' {
  interface CustomTypeOptions {
    defaultNS: 'common';
    resources: Messages;
  }
}

export interface I18nConfig {
  locale: Locale;
  /** Имя продукта из конфига приложения, кириллицей («Соседи»); для sr-Latn транслитерируется. */
  appName: string;
}

/** Бэкенд i18next: неймспейсы, которых нет сразу (сербский), — из чанка. */
const lazyCatalogs: BackendModule = {
  type: 'backend',
  init: () => undefined,
  read: (language, namespace, callback) => {
    if (!isLocale(language) || !isNamespace(namespace)) {
      callback(null, {});
      return;
    }
    loadNamespace(language, namespace).then(
      (catalog) => callback(null, catalog),
      (error: unknown) => callback(error as Error, null),
    );
  },
};

function appNameFor(locale: string, appName: string): string {
  return locale === 'sr-Latn' ? cyrToLat(appName) : appName;
}

export function createI18n({ locale, appName }: I18nConfig): I18n {
  // i18next хранит ссылку на этот объект: при смене языка меняем значение на месте
  const defaultVariables = { appName: appNameFor(locale, appName) };
  const instance = i18next.createInstance();
  instance.use(lazyCatalogs).use(ICU).use(initReactI18next);
  void instance.init({
    lng: locale,
    fallbackLng: DEFAULT_LOCALE,
    supportedLngs: [...LOCALES],
    load: 'currentOnly',
    ns: [...FIRST_SCREEN],
    defaultNS: 'common',
    resources: EAGER,
    partialBundledLanguages: true,
    initAsync: false,
    returnNull: false,
    interpolation: { escapeValue: false, defaultVariables },
  });
  instance.on('languageChanged', (lng) => {
    defaultVariables.appName = appNameFor(lng, appName);
  });
  return instance;
}

export function currentLocale(instance: I18n): Locale {
  return isLocale(instance.language) ? instance.language : DEFAULT_LOCALE;
}

/** Тексты первого экрана текущего языка загружены: на сербском — после чанка, на русском —
 *  сразу. Без сети чанк не придёт — тогда тексты русские (fallbackLng), а не пустой экран. */
export function i18nReady(instance: I18n): Promise<void> {
  return instance.loadNamespaces([...FIRST_SCREEN]).catch(() => undefined);
}

/** Остальные неймспейсы — заранее, пока человек смотрит первый экран: переход на экран мастера
 *  или онбординга не ждёт сети. Ошибка — не беда: экран загрузит свой неймспейс сам. */
export function preloadCatalogs(instance: I18n): Promise<void> {
  return instance.loadNamespaces([...NAMESPACES]).catch(() => undefined);
}
