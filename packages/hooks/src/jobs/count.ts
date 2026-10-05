// Сколько заявок (DEVELOPMENT_PLAN 5.3): «Показать N» шторки S14 и «N новых задач рядом» на
// Главной — теми же фильтрами, что лента. Отдельно от ленты: Главной не нужны страницы и «не
// подходит» (бюджет первого экрана).
import { getJobsCountJobsQueryKey, jobsCountJobs } from '@sosed/api-client';
import { keepPreviousData, queryOptions, useQuery } from '@tanstack/react-query';

import type { FeedQuery } from './feed.ts';

/** «N новых задач рядом» на Главной: новые — опубликованные за сутки. */
export const NEW_JOBS_HOURS = 24;

/** Запрос числа — один у хука и у предзагрузки Главной после входа. */
export function jobsCountQueryOptions(query: FeedQuery | null, newHours?: number) {
  const params = query ? { ...query, ...(newHours ? { new_hours: newHours } : {}) } : null;
  return queryOptions({
    queryKey: getJobsCountJobsQueryKey(params ?? { city_id: 0 }),
    queryFn: ({ signal }) => {
      if (params === null) throw new Error('count is disabled without a city');
      return jobsCountJobs(params, { signal });
    },
    enabled: params !== null,
  });
}

/** `newHours` — только опубликованные за последние часы (Главная); `null` — города ещё нет. */
export function useJobsCount(query: FeedQuery | null, newHours?: number) {
  return useQuery({ ...jobsCountQueryOptions(query, newHours), placeholderData: keepPreviousData });
}
