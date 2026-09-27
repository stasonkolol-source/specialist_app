// Сборка приложения до первого рендера: платформа и ready() как можно раньше, язык из launch
// params, клиент API, вход по initData в фоне (после входа — язык, сохранённый на сервере),
// цель deep link запуска (S01). Тот же код собирает приложение в тестах.
import { ApiError, configureApiClient, getIdentityGetMeQueryKey } from '@sosed/api-client';
import { createI18n, currentLocale, isLocale, resolveLocale } from '@sosed/i18n';
import type { Platform } from '@sosed/platform';
import type { QueryClient } from '@tanstack/react-query';
import type { RouterHistory } from '@tanstack/react-router';

import { ONBOARDING_PATHS } from '../features/onboarding/index.ts';
import { RESTRICTED_PATH, reportSystemError } from '../features/service/s49-system/index.ts';
import { startTarget } from '../routes/startapp.ts';
import { openedByTelegram } from './launch.ts';
import { createQueryClient } from './query.ts';
import { createAppRouter, historyFor } from './router.ts';
import type { Auth } from './session.ts';
import { createAuth } from './session.ts';

export const APP_NAME = 'Соседи';

export interface Assembled {
  platform: Platform;
  i18n: ReturnType<typeof createI18n>;
  queryClient: QueryClient;
  router: ReturnType<typeof createAppRouter>;
  version: string;
  signIn: () => Promise<boolean>;
  /** Вход при запуске (S01): main.tsx начинает его сразу, LaunchGate ждёт итог. */
  launch: Auth['launch'];
  /** Экран deep link этого запуска; `null` — открыли без него или перезагрузили экран. */
  deepLink: string | null;
}

export interface AssembleOptions {
  version: string;
  history?: RouterHistory;
  languages?: readonly string[];
  /**
   * Сохранённый выбор языка до входа: в mock-режиме — `?locale=`. В Telegram его нет —
   * `ui_locale` пользователя приходит с входом и применяется после него.
   */
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
  // смена языка на экране (S31, позже S43) — без перезагрузки: lang страницы следует за i18n
  i18n.on('languageChanged', (next) => {
    document.documentElement.lang = next;
  });
  // hash читаем до роутера: при запуске из Telegram в нём launch params, а не путь
  const deepLink = openedByTelegram(platform.kind, window.location.hash)
    ? startTarget(platform.launch.startParam)
    : null;
  // S49 из ответов API: 426, техработы и санкция на аккаунт закрывают приложение (StartupGate),
  // частичная санкция действия открывает S49b поверх экрана. 403 `consent_required` — создающее
  // действие без согласия с действующими правилами (сменилась редакция, пока приложение открыто):
  // S02c и обратно на этот экран
  const onSystemError = (error: unknown) => {
    if (error instanceof ApiError && error.code === 'consent_required') {
      void queryClient.invalidateQueries({ queryKey: getIdentityGetMeQueryKey() });
      const next = router.state.location.href;
      void router.navigate({ to: ONBOARDING_PATHS.rules, search: { next } });
      return;
    }
    if (reportSystemError(error)) void router.navigate({ to: RESTRICTED_PATH });
  };
  const queryClient = createQueryClient(onSystemError);
  // /me живёт всю сессию: по нему охрана маршрутов (routes/guards.ts) решает онбординг и согласие,
  // а экраны, которые на него подписаны, открыты не всегда. Со сборкой мусора по умолчанию
  // (5 минут без подписчиков) S02c после долгого чтения S48 уводил бы на главную, а «+» пускал
  // без согласия
  queryClient.setQueryDefaults(getIdentityGetMeQueryKey(), { gcTime: Infinity });
  const router = createAppRouter(options.history ?? historyFor(platform.kind), queryClient);
  // ui_locale — выбор пользователя, на нём же пишет бот: важнее language_code Telegram.
  // en в MVP не выбирается — тогда остаётся язык из launch params
  const auth = createAuth(
    platform,
    ({ ui_locale }) => {
      if (isLocale(ui_locale) && ui_locale !== i18n.language) void i18n.changeLanguage(ui_locale);
    },
    onSystemError,
  );
  configureApiClient({
    client: `tma/${options.version}`,
    locale: () => currentLocale(i18n),
    onReauth: auth.signIn,
    baseUrl: options.baseUrl ?? '',
  });
  return {
    platform,
    i18n,
    queryClient,
    router,
    version: options.version,
    signIn: auth.signIn,
    launch: auth.launch,
    deepLink,
  };
}
