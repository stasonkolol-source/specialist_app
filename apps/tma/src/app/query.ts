// QueryClient — синглтон точки сборки. Без refetch при фокусе и pull-to-refresh: Mini App
// сворачивается и разворачивается постоянно, а свежесть данных держат staleTime и инвалидации.
// networkMode 'always': без сети запрос падает NetworkError и экран показывает S49a с «Повторить».
// По умолчанию ('online') React Query молча ставит запрос на паузу — вечный скелетон вместо S49a.
// Сеть вернулась — устаревшие запросы перечитываются сами (refetchOnReconnect).
import { ApiError, MaintenanceError } from '@sosed/api-client';
import { MutationCache, QueryCache, QueryClient } from '@tanstack/react-query';

const MAX_RETRIES = 2;

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
  return new QueryClient({
    queryCache: new QueryCache({
      onError: (error, query) => {
        if (query.meta?.silent === true && query.getObserversCount() === 0) return;
        onError(error);
      },
    }),
    mutationCache: new MutationCache({ onError }),
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        refetchOnWindowFocus: false,
        retry: shouldRetry,
        networkMode: 'always',
      },
      mutations: { retry: false, networkMode: 'always' },
    },
  });
}
