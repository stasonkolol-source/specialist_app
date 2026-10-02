// Лента заявок исполнителя (S13–S15, DEVELOPMENT_PLAN 5.3): страницы по курсору; «Не интересно»
// убирает заявку из загруженных страниц сразу и перечитывает ленту. Счётчик — в count.ts: его
// берёт и Главная, которой лента не нужна (бюджет первого экрана).
import type { JobCardOut, JobsListJobsParams, JobsPageOut } from '@sosed/api-client';
import {
  getJobsCountJobsQueryKey,
  getJobsListJobsQueryKey,
  jobsHideJob,
  jobsListJobs,
} from '@sosed/api-client';
import type { InfiniteData } from '@tanstack/react-query';
import {
  keepPreviousData,
  useInfiniteQuery,
  useMutation,
  useQueryClient,
} from '@tanstack/react-query';

export const FEED_PAGE_SIZE = 20;

/** Запрос ленты без страницы: город и фильтры. */
export type FeedQuery = Omit<JobsListJobsParams, 'limit' | 'cursor'>;
export type FeedPages = InfiniteData<JobsPageOut, string | null>;

/** Все ленты — с любыми фильтрами: «не интересно» убирает заявку из каждой. */
export const FEED_KEY = getJobsListJobsQueryKey().slice(0, 1);
/** Все счётчики «N заявок» и «Показать N». */
const COUNT_KEY = getJobsCountJobsQueryKey().slice(0, 1);

export const feedQueryKey = (query: FeedQuery) => getJobsListJobsQueryKey(query);

/** `null` — запрашивать нечего (город ещё не известен). */
export function useJobsFeed(query: FeedQuery | null) {
  return useInfiniteQuery({
    queryKey: feedQueryKey(query ?? { city_id: 0 }),
    queryFn: ({ pageParam, signal }) => {
      if (query === null) throw new Error('feed is disabled without a city');
      return jobsListJobs(
        pageParam === null
          ? { ...query, limit: FEED_PAGE_SIZE }
          : { ...query, limit: FEED_PAGE_SIZE, cursor: pageParam },
        { signal },
      );
    },
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor ?? null,
    enabled: query !== null,
    placeholderData: keepPreviousData,
  });
}

/** Карточки всех загруженных страниц подряд. */
export function jobCards(feed: Pick<FeedPages, 'pages'> | undefined): JobCardOut[] {
  return feed?.pages.flatMap((page) => page.items) ?? [];
}

/** «Не интересно» (S15): заявка сразу пропадает из загруженных лент, потом ленты и счётчики
 *  перечитываются. */
export function useHideJob() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (jobId: string) => jobsHideJob(jobId),
    onMutate: (jobId) => {
      client.setQueriesData<FeedPages>({ queryKey: FEED_KEY }, (data) =>
        data
          ? {
              ...data,
              pages: data.pages.map((page) => ({
                ...page,
                items: page.items.filter((item) => item.id !== jobId),
              })),
            }
          : data,
      );
    },
    onSettled: async () => {
      await Promise.all([
        client.invalidateQueries({ queryKey: FEED_KEY }),
        client.invalidateQueries({ queryKey: COUNT_KEY }),
      ]);
    },
  });
}
