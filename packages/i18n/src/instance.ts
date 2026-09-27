// Экземпляр i18next с ICU. Создаётся один раз в apps/tma/src/app и передаётся провайдером (ADR-0020 §13).
import i18next from 'i18next';
import type { i18n as I18n } from 'i18next';
import ICU from 'i18next-icu';
import { initReactI18next } from 'react-i18next';

import type { Locale } from './locale.ts';
import { DEFAULT_LOCALE, LOCALES, isLocale } from './locale.ts';
import type { Messages } from './resources.ts';
import { NAMESPACES, RESOURCES } from './resources.ts';
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

function appNameFor(locale: string, appName: string): string {
  return locale === 'sr-Latn' ? cyrToLat(appName) : appName;
}

export function createI18n({ locale, appName }: I18nConfig): I18n {
  // i18next хранит ссылку на этот объект: при смене языка меняем значение на месте
  const defaultVariables = { appName: appNameFor(locale, appName) };
  const instance = i18next.createInstance();
  instance.use(ICU).use(initReactI18next);
  void instance.init({
    lng: locale,
    fallbackLng: DEFAULT_LOCALE,
    supportedLngs: [...LOCALES],
    load: 'currentOnly',
    ns: [...NAMESPACES],
    defaultNS: 'common',
    resources: RESOURCES,
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
