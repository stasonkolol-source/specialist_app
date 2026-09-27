// QueryClient — синглтон точки сборки. Без refetch при фокусе и pull-to-refresh: Mini App
// сворачивается и разворачивается постоянно, а свежесть данных держат staleTime и инвалидации.
import { ApiError, UpgradeRequiredError } from '@sosed/api-client';
import { MutationCache, QueryCache, QueryClient } from '@tanstack/react-query';

const MAX_RETRIES = 2;

/** 4xx не повторяем: ответ не изменится. Сеть и 5xx — до двух повторов. */
export function shouldRetry(failureCount: number, error: unknown): boolean {
  if (error instanceof ApiError && error.status < 500) return false;
  return failureCount < MAX_RETRIES;
}

/** `onUpgradeRequired` — любой запрос получил 426: приложение показывает экран обновления. */
export function createQueryClient(onUpgradeRequired: () => void = () => undefined): QueryClient {
  const onError = (error: unknown) => {
    if (error instanceof UpgradeRequiredError) onUpgradeRequired();
  };
  return new QueryClient({
    queryCache: new QueryCache({ onError }),
    mutationCache: new MutationCache({ onError }),
    defaultOptions: {
      queries: { staleTime: 30_000, refetchOnWindowFocus: false, retry: shouldRetry },
      mutations: { retry: false },
    },
  });
}
