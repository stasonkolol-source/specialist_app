// Роутер: в Telegram — hash history (URL Mini App не меняется, перезагрузка внутри клиента
// возвращает на тот же экран), в браузере — обычная, в тестах — memory.
import type { PlatformKind } from '@sosed/platform';
import type { RouterHistory } from '@tanstack/react-router';
import {
  createBrowserHistory,
  createHashHistory,
  createMemoryHistory,
  createRouter,
} from '@tanstack/react-router';

import { routeTree } from '../routes/tree.tsx';

export function historyFor(kind: PlatformKind, initialPath = '/'): RouterHistory {
  if (kind === 'tma') return createHashHistory();
  if (kind === 'browser') return createBrowserHistory();
  return createMemoryHistory({ initialEntries: [initialPath] });
}

export function createAppRouter(history: RouterHistory) {
  return createRouter({ routeTree, history, defaultPreload: 'intent', scrollRestoration: true });
}

declare module '@tanstack/react-router' {
  interface Register {
    router: ReturnType<typeof createAppRouter>;
  }
}
