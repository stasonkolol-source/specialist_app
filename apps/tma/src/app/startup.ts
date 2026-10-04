// Запуск без ожидания React (S01, DEVELOPMENT_PLAN 4.8 — холодный старт < 2,5 с): сразу после
// сборки, параллельно со входом, — client-config (его ждёт StartupGate), справочники Главной и
// чанк экрана запуска. Как только вход решил город, — данные Главной (warm.ts, своим чанком).
// Ключи и свежесть — из фабрик @sosed/hooks: те же, что у хуков экранов, запрос не задвоится. Конфиг
// и справочники прошлого запуска (persist.ts) поднимаются раньше запросов: экран рисуется по ним, а
// запросы освежают их в фоне.
import { categoriesQueryOptions, citiesQueryOptions, clientConfigQueryOptions } from '@sosed/hooks';
import { currentLocale } from '@sosed/i18n';

import type { Assembled } from './bootstrap.ts';
import { launchHref, launchTarget } from './launch.ts';
import { persistPublicQueries, restorePublicQueries } from './persist.ts';

const HOME = '/';

export function startLaunch(app: Assembled): void {
  const { queryClient, router, i18n, deepLink } = app;
  const locale = currentLocale(i18n);
  restorePublicQueries(queryClient, app.version);
  persistPublicQueries(queryClient, app.version);
  // вход — сразу: экран запуска S01 (LaunchGate) дождётся того же итога
  const launched = app.launch();
  void queryClient.prefetchQuery(clientConfigQueryOptions());
  void queryClient.prefetchQuery(citiesQueryOptions(locale));
  void queryClient.prefetchQuery(categoriesQueryOptions(locale));
  // адрес запуска — до входа: LaunchGate после него уже заменит его на экран первого кадра
  const location = { ...router.history.location };
  // чанк экрана запуска (обычно Главная, иначе — deep link): в Telegram путь роутера — launch
  // params, поэтому цель, а не текущий путь
  const href = launchTarget(location, deepLink);
  // адрес строкой (с ?next=): buildLocation разбирает href сам, `to` при нём не нужен
  void router
    .preloadRoute({ href } as Parameters<typeof router.preloadRoute>[0])
    .catch(() => undefined);
  void launched.then((result) => {
    // вне Telegram Главной нет (8.1): вместо неё — «Открыть в Telegram», её данные не нужны
    if (result.kind === 'failed' || app.platform.kind === 'browser') return;
    const user = result.kind === 'signed-in' ? result.user : null;
    // первый экран — Главная (не онбординг и не deep link): её данные — вместе с её чанком
    if ((launchHref(user, location, deepLink) ?? location.href) !== HOME) return;
    void import('./warm.ts').then((module) =>
      module.warmHome(queryClient, currentLocale(i18n), user),
    );
  });
}
