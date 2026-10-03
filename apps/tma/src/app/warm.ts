// Данные Главной сразу после входа (app/startup.ts): город известен — «Свободны сегодня рядом»,
// «Ищете подработку?» и свои заявки запрашиваются вместе с отрисовкой S03, а не после того, как
// её блоки смонтируются. Город — тот же, что у Главной (catalog/shared/city.ts): свой у вошедшего,
// иначе первый открытый. Своим чанком: первому экрану этот код не нужен. Ошибки — тихие (SILENT):
// Главная перечитает свой запрос сама.
import type { MeOut } from '@sosed/api-client';
import type { Locale } from '@sosed/i18n';
import {
  NEW_JOBS_HOURS,
  availableTodayQueryOptions,
  citiesQueryOptions,
  defaultCity,
  jobsCountQueryOptions,
  myJobsQueryOptions,
} from '@sosed/hooks';
import type { QueryClient } from '@tanstack/react-query';

import { SILENT } from './query.ts';

export async function warmHome(
  queryClient: QueryClient,
  locale: Locale,
  user: MeOut | null,
): Promise<void> {
  if (user) void queryClient.prefetchQuery({ ...myJobsQueryOptions(), meta: SILENT });
  // города уже запрошены при запуске: здесь — тот же запрос или ответ из кэша
  const cities = await queryClient
    .fetchQuery({ ...citiesQueryOptions(locale), meta: SILENT })
    .catch(() => null);
  const cityId = cities ? defaultCity(cities, user?.home_city_id ?? null) : null;
  if (cityId === null) return;
  void queryClient.prefetchQuery({
    ...availableTodayQueryOptions(locale, cityId, null),
    meta: SILENT,
  });
  void queryClient.prefetchQuery({
    ...jobsCountQueryOptions({ city_id: cityId }, NEW_JOBS_HOURS),
    meta: SILENT,
  });
}
