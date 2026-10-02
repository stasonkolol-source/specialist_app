// Сколько заявок (DEVELOPMENT_PLAN 5.3): «Показать N» шторки S14 и «N новых задач рядом» на
// Главной — теми же фильтрами, что лента. Отдельно от ленты: Главной не нужны страницы и «не
// интересно» (бюджет первого экрана).
import { getJobsCountJobsQueryKey, jobsCountJobs } from '@sosed/api-client';
import { keepPreviousData, useQuery } from '@tanstack/react-query';

import type { FeedQuery } from './feed.ts';

/** `newHours` — только опубликованные за последние часы (Главная); `null` — города ещё нет. */
export function useJobsCount(query: FeedQuery | null, newHours?: number) {
  const params = query ? { ...query, ...(newHours ? { new_hours: newHours } : {}) } : null;
  return useQuery({
    queryKey: getJobsCountJobsQueryKey(params ?? { city_id: 0 }),
    queryFn: ({ signal }) => {
      if (params === null) throw new Error('count is disabled without a city');
      return jobsCountJobs(params, { signal });
    },
    enabled: params !== null,
    placeholderData: keepPreviousData,
  });
}
