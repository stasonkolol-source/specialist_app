// Намерение перейти — палец лёг на ссылку (pointerdown) или фокус с клавиатуры: чанк экрана и его
// главный запрос начинают грузиться до click. TanStack <Link> этого не даст: переходы приложения
// идут router.navigate с обычных <a> (TabBar, карточки — компоненты ui-web без роутера). Поэтому —
// один слушатель на документ: href ссылки → путь маршрута → его чанк, а данные экрана —
// prefetch.ts (своим чанком, первому экрану он не нужен). И в простое после перехода — чанк
// экрана, который с этого открывают чаще всего (NEXT): нажатие не ждёт сети.
import { CARD_PATHS, CATALOG_PATHS } from '../features/catalog/index.ts';
import { JOBS_PATHS } from '../features/jobs/index.ts';
import { MESSAGES_PATHS } from '../features/messages/index.ts';
import { saveData, whenIdle } from '../features/shell/index.ts';
import type { Assembled } from './bootstrap.ts';

/** Экран → куда с него идут дальше: список → подробности, заявка → отклик, отклик → сделка. */
const NEXT: Readonly<Record<string, readonly string[]>> = {
  '/': [CARD_PATHS.profile],
  [CATALOG_PATHS.results]: [CARD_PATHS.profile],
  [JOBS_PATHS.feed]: [JOBS_PATHS.job],
  [JOBS_PATHS.job]: [JOBS_PATHS.respond],
  [JOBS_PATHS.mine]: [JOBS_PATHS.manage],
  [JOBS_PATHS.manage]: [JOBS_PATHS.response],
  [JOBS_PATHS.response]: [JOBS_PATHS.deal],
  [MESSAGES_PATHS.list]: [MESSAGES_PATHS.chat],
};

/** Путь маршрута из href ссылки: у hash history в Telegram href — «/?…#/экран», в браузере —
 *  сам путь. Внешние ссылки и якоря на странице — `null`. */
export function routeOf(href: string): string | null {
  const hash = href.indexOf('#');
  const path = hash >= 0 ? href.slice(hash + 1) : href;
  return path.startsWith('/') && !path.startsWith('//') ? path : null;
}

export function listenIntent(app: Pick<Assembled, 'router' | 'queryClient' | 'i18n'>): () => void {
  const { router } = app;
  const onIntent = (event: Event) => {
    const anchor = event.target instanceof Element ? event.target.closest('a[href]') : null;
    const href = anchor ? routeOf(anchor.getAttribute('href') ?? '') : null;
    if (!href) return;
    // адрес строкой (с ?…): buildLocation разбирает href сам, `to` при нём не нужен
    void router
      .preloadRoute({ href } as Parameters<typeof router.preloadRoute>[0])
      .catch(() => undefined);
    void import('./prefetch.ts')
      .then((module) => module.prefetchScreen(app, href))
      .catch(() => undefined);
  };
  document.addEventListener('pointerdown', onIntent, { capture: true, passive: true });
  document.addEventListener('focusin', onIntent);
  let cancelIdle: (() => void) | null = null;
  // экран открылся — чанк следующего в простое; с Data Saver — нет: загрузится по нажатию
  const unsubscribe = router.subscribe('onResolved', ({ toLocation }) => {
    cancelIdle?.();
    cancelIdle = null;
    if (saveData()) return;
    const [, , route] = router.getMatchedRoutes(toLocation.pathname);
    const next = (route && NEXT[route.fullPath]) ?? [];
    if (next.length === 0) return;
    cancelIdle = whenIdle(() => {
      for (const id of next) {
        const target = router.routesById[id as keyof typeof router.routesById];
        if (target) void router.loadRouteChunk(target)?.catch(() => undefined);
      }
    });
  });
  return () => {
    document.removeEventListener('pointerdown', onIntent, { capture: true });
    document.removeEventListener('focusin', onIntent);
    unsubscribe();
    cancelIdle?.();
  };
}
