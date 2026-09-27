// Сборка приложения до первого рендера: платформа и ready() как можно раньше, язык из launch
// params, клиент API, вход по initData в фоне. Тот же код собирает приложение в тестах.
import { configureApiClient } from '@sosed/api-client';
import { createI18n, currentLocale, resolveLocale } from '@sosed/i18n';
import type { Platform } from '@sosed/platform';
import type { QueryClient } from '@tanstack/react-query';
import type { RouterHistory } from '@tanstack/react-router';

import { createQueryClient } from './query.ts';
import { createAppRouter, historyFor } from './router.ts';
import { createAuth } from './session.ts';
import { useUpgradeStore } from './upgrade.ts';

export const APP_NAME = 'Сосед';

export interface Assembled {
  platform: Platform;
  i18n: ReturnType<typeof createI18n>;
  queryClient: QueryClient;
  router: ReturnType<typeof createAppRouter>;
  version: string;
  signIn: () => Promise<boolean>;
}

export interface AssembleOptions {
  version: string;
  history?: RouterHistory;
  languages?: readonly string[];
  /** Язык, выбранный пользователем (`/me.language`); в mock-режиме — `?locale=`. */
  savedLocale?: string | null;
  /** Origin API; в приложении — тот же, что у страницы (пусто), в тестах — абсолютный. */
  baseUrl?: string;
}

export function assemble(platform: Platform, options: AssembleOptions): Assembled {
  platform.ready();
  platform.expand();
  const locale = resolveLocale({
    saved: options.savedLocale,
    telegram: platform.launch.languageCode,
    browser: options.languages ?? [],
  });
  const i18n = createI18n({ locale, appName: APP_NAME });
  document.documentElement.lang = locale;
  const auth = createAuth(platform);
  configureApiClient({
    client: `tma/${options.version}`,
    locale: () => currentLocale(i18n),
    onReauth: auth.signIn,
    baseUrl: options.baseUrl ?? '',
  });
  return {
    platform,
    i18n,
    queryClient: createQueryClient(() => useUpgradeStore.getState().force('app')),
    router: createAppRouter(options.history ?? historyFor(platform.kind)),
    version: options.version,
    signIn: auth.signIn,
  };
}
