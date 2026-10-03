// Роутер: в Telegram — hash history (URL Mini App не меняется, перезагрузка внутри клиента
// возвращает на тот же экран), в браузере — обычная, в тестах — memory.
import type { PlatformKind } from '@sosed/platform';
import type { QueryClient } from '@tanstack/react-query';
import type { AnyRouter, RouterHistory } from '@tanstack/react-router';
import {
  createBrowserHistory,
  createHashHistory,
  createMemoryHistory,
  createRouter,
} from '@tanstack/react-router';

import { routeTree } from '../routes/tree.tsx';
import { RoutePending } from './RoutePending.tsx';

/** Чанк экрана грузится дольше — видна полоса ожидания; быстрый переход её не показывает. */
const PENDING_MS = 150;
/** Показали полосу — не дольше нужного: экран открывается сразу, как готов. */
const PENDING_MIN_MS = 0;

export function historyFor(kind: PlatformKind, initialPath = '/'): RouterHistory {
  if (kind === 'tma') return createHashHistory();
  if (kind === 'browser') return createBrowserHistory();
  return createMemoryHistory({ initialEntries: [initialPath] });
}

/** Контекст маршрутов: охрана (routes/guards.ts) читает /me из кэша QueryClient. */
export function createAppRouter(history: RouterHistory, queryClient: QueryClient) {
  return createRouter({
    routeTree,
    history,
    context: { queryClient },
    defaultPreload: 'intent',
    defaultPendingComponent: RoutePending,
    defaultPendingMs: PENDING_MS,
    defaultPendingMinMs: PENDING_MIN_MS,
    scrollRestoration: true,
    // Ошибка рендера экрана — к ErrorBoundary приложения (S49 с «Повторить»), а не в запасной
    // экран TanStack по-английски
    disableGlobalCatchBoundary: true,
  });
}

/** «Повторить» после ошибки рендера: заново загрузить чанки экранов текущего адреса и перечитать
 *  маршруты. lazyRouteComponent забывает неудачный импорт только при повторной загрузке — без неё
 *  экран бросил бы ту же ошибку. Снова не загрузилось — экран бросит её, и S49 покажется опять. */
export async function reloadRoutes(router: AnyRouter): Promise<void> {
  await Promise.allSettled(
    router.state.matches.map((match) => router.loadRouteChunk(router.routesById[match.routeId])),
  );
  void router.invalidate();
}

declare module '@tanstack/react-router' {
  interface Register {
    router: ReturnType<typeof createAppRouter>;
  }
}
