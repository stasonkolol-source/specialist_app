// QueryClient — синглтон точки сборки. Без refetch при фокусе и pull-to-refresh: Mini App
// сворачивается и разворачивается постоянно, а свежесть данных держат staleTime и инвалидации.
// networkMode 'always': без сети запрос падает NetworkError и экран показывает S49a с «Повторить».
// По умолчанию ('online') React Query молча ставит запрос на паузу — вечный скелетон вместо S49a.
// Сеть вернулась — устаревшие запросы перечитываются сами (refetchOnReconnect).
// Свежесть: ленты, выдача, чаты, свои заявки и отклики — 30 с (меняются чужими действиями); своё,
// что меняется только своими действиями, — 5 минут (OWN); справочники — час (@sosed/hooks).
// Неиспользуемое живёт 30 минут: «Назад» через долгое время — сразу экран из кэша, а не скелетон.
import {
  ApiError,
  MaintenanceError,
  getIdentityGetMeQueryKey,
  getJobsListResponseTemplatesQueryKey,
  getJobsListSavedJobsQueryKey,
  getPricingListMyServicesQueryKey,
  getSearchListFavoritesQueryKey,
  getSpecialistsGetMyProfileQueryKey,
} from '@sosed/api-client';
import { MutationCache, QueryCache, QueryClient } from '@tanstack/react-query';

const MAX_RETRIES = 2;
const STALE_MS = 30_000;
const GC_MS = 30 * 60_000;
/** Своё, что меняется только своими действиями: их ответы сразу ложатся в кэш. */
const OWN_STALE_MS = 5 * 60_000;
/** Избранное (сердечки и S12), сохранённые заявки, свой профиль специалиста и его прайс, шаблоны
 *  откликов. Ключи — префиксы: GET /me/profile/… тоже. */
const OWN = [
  getSearchListFavoritesQueryKey(),
  getJobsListSavedJobsQueryKey(),
  getSpecialistsGetMyProfileQueryKey(),
  getPricingListMyServicesQueryKey(),
  getJobsListResponseTemplatesQueryKey(),
];

/** 4xx и техработы не повторяем: ответ не изменится. Сеть и прочие 5xx — до двух повторов. */
export function shouldRetry(failureCount: number, error: unknown): boolean {
  if (error instanceof ApiError && error.status < 500) return false;
  if (error instanceof MaintenanceError) return false;
  return failureCount < MAX_RETRIES;
}

/** Предзагрузка «на всякий случай» (данные Главной после входа, экран по намерению): пока её
 *  ответ никто не ждёт, ошибка не открывает экраны S49. Экран, который смонтируется, перечитает
 *  запрос сам — и ошибку покажет как обычно. */
export const SILENT = { silent: true } as const;

/** `onError` — ошибка любого запроса после повторов: 426, техработы и санкции решают экраны S49. */
export function createQueryClient(
  onError: (error: unknown) => void = () => undefined,
): QueryClient {
  const client = new QueryClient({
    queryCache: new QueryCache({
      onError: (error, query) => {
        if (query.meta?.silent === true && query.getObserversCount() === 0) return;
        onError(error);
      },
    }),
    mutationCache: new MutationCache({ onError }),
    defaultOptions: {
      queries: {
        staleTime: STALE_MS,
        gcTime: GC_MS,
        refetchOnWindowFocus: false,
        retry: shouldRetry,
        networkMode: 'always',
      },
      mutations: { retry: false, networkMode: 'always' },
    },
  });
  for (const queryKey of OWN) client.setQueryDefaults(queryKey, { staleTime: OWN_STALE_MS });
  // /me живёт всю сессию: по нему охрана маршрутов (routes/guards.ts) решает онбординг и согласие,
  // а экраны, которые на него подписаны, открыты не всегда. Со сборкой мусора S02c после долгого
  // чтения S48 уводил бы на главную, а «+» пускал без согласия. Ответ входа и свои правки кладут
  // его в кэш сами — перечитывать при каждом экране незачем
  client.setQueryDefaults(getIdentityGetMeQueryKey(), {
    gcTime: Infinity,
    staleTime: OWN_STALE_MS,
  });
  return client;
}
