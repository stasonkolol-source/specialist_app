// Отзывы (S27, S28, S11; DEVELOPMENT_PLAN 7.3): оставить отзыв по сделке, ответить на отзыв о
// себе, «Мои отзывы» (полученные и написанные), «Сделки и отзывы» — свои сделки в обеих ролях
// с отзывом по каждой. После отзыва перечитываются сделка и списки; отзыв на карточке
// специалиста появится после проверки.
import type {
  HistoryPageOut,
  MyReviewsPageOut,
  ReplyIn,
  ReviewIn,
  ReviewsDirection,
} from '@sosed/api-client';
import {
  getReviewsListMyReviewsQueryKey,
  getSession,
  getViewsListDealHistoryQueryKey,
  reviewsLeaveReview,
  reviewsListMyReviews,
  reviewsReplyToReview,
  viewsListDealHistory,
} from '@sosed/api-client';
import type { InfiniteData } from '@tanstack/react-query';
import {
  keepPreviousData,
  useInfiniteQuery,
  useMutation,
  useQueryClient,
} from '@tanstack/react-query';

import { dealCardQueryKey } from '../deals/deals.ts';

export const HISTORY_PAGE_SIZE = 20;
export const MY_REVIEWS_PAGE_SIZE = 20;
export type HistoryPages = InfiniteData<HistoryPageOut, string | null>;
export type MyReviewsPages = InfiniteData<MyReviewsPageOut, string | null>;

/** Префикс «Сделок и отзывов» S28. */
export const DEAL_HISTORY_KEY = getViewsListDealHistoryQueryKey().slice(0, 1);
/** Префикс «Моих отзывов» любой вкладки. */
export const MY_REVIEWS_KEY = getReviewsListMyReviewsQueryKey().slice(0, 1);

/** S28 «Сделки»: свои сделки клиентом и исполнителем, новые первыми. */
export function useDealHistory() {
  return useInfiniteQuery({
    queryKey: getViewsListDealHistoryQueryKey(),
    queryFn: ({ pageParam, signal }) =>
      viewsListDealHistory(
        { limit: HISTORY_PAGE_SIZE, ...(pageParam ? { cursor: pageParam } : {}) },
        { signal },
      ),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor ?? null,
    enabled: getSession() !== null,
  });
}

/** S28 «Отзывы»: полученные (обо мне) или написанные. */
export function useMyReviews(direction: ReviewsDirection) {
  return useInfiniteQuery({
    queryKey: getReviewsListMyReviewsQueryKey({ direction }),
    queryFn: ({ pageParam, signal }) =>
      reviewsListMyReviews(
        {
          direction,
          limit: MY_REVIEWS_PAGE_SIZE,
          ...(pageParam ? { cursor: pageParam } : {}),
        },
        { signal },
      ),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor ?? null,
    placeholderData: keepPreviousData,
    enabled: getSession() !== null,
  });
}

/** Элементы всех загруженных страниц подряд. */
export function pagedItems<T>(pages: { pages: { items: T[] }[] } | undefined): T[] {
  return pages?.pages.flatMap((page) => page.items) ?? [];
}

/** S27: отзыв по завершённой сделке — ждёт проверки, потом виден на карточке. */
export function useLeaveReview(dealId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: ReviewIn) => reviewsLeaveReview(dealId, body),
    // «Спасибо» — сразу по ответу сервера; сделка и списки перечитываются в фоне
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: dealCardQueryKey(dealId) });
      void client.invalidateQueries({ queryKey: DEAL_HISTORY_KEY });
      void client.invalidateQueries({ queryKey: MY_REVIEWS_KEY });
    },
  });
}

/** S28: ответ на отзыв о себе — один, виден после проверки. */
export function useReplyToReview() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ reviewId, body }: { reviewId: string; body: ReplyIn }) =>
      reviewsReplyToReview(reviewId, body),
    onSuccess: () => void client.invalidateQueries({ queryKey: MY_REVIEWS_KEY }),
  });
}
