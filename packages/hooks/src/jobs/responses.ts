// Отклики исполнителя (S15–S17, DEVELOPMENT_PLAN 5.5): отправить с ключом идемпотентности формы —
// повтор после обрыва сети вернёт тот же отклик; поправить и отозвать, пока клиент не решил. «Мои
// отклики» — страницы по курсору, чип — группа. После любого изменения (и после ошибки: место могли
// занять) перечитываются заявка — места и «Вы откликнулись», — лента и «Мои отклики»: в фоне,
// экран отклика уходит на «Мои отклики» сразу по ответу сервера.
import type {
  MyResponseOut,
  MyResponsesPageOut,
  ResponseGroup,
  ResponseIn,
  ResponseOfferIn,
} from '@sosed/api-client';
import {
  getJobsGetResponseQueryKey,
  getJobsListMyResponsesQueryKey,
  jobsGetResponse,
  jobsListMyResponses,
  jobsRespond,
  jobsReviseResponse,
  jobsWithdrawResponse,
} from '@sosed/api-client';
import type { InfiniteData, QueryClient } from '@tanstack/react-query';
import {
  keepPreviousData,
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query';

import { FEED_KEY } from './feed.ts';
import { jobQueryKey } from './jobs.ts';

export const MY_RESPONSES_PAGE_SIZE = 20;
export type MyResponsesPages = InfiniteData<MyResponsesPageOut, string | null>;

/** «Мои отклики» с любым чипом. */
export const MY_RESPONSES_KEY = getJobsListMyResponsesQueryKey().slice(0, 1);

export const myResponsesQueryKey = (group: ResponseGroup | null) =>
  getJobsListMyResponsesQueryKey(group ? { status: group } : undefined);

/** `group` null — все отклики (чип «Все»). */
export function useMyResponses(group: ResponseGroup | null) {
  return useInfiniteQuery({
    queryKey: myResponsesQueryKey(group),
    queryFn: ({ pageParam, signal }) =>
      jobsListMyResponses(
        {
          ...(group ? { status: group } : {}),
          limit: MY_RESPONSES_PAGE_SIZE,
          ...(pageParam ? { cursor: pageParam } : {}),
        },
        { signal },
      ),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor ?? null,
    placeholderData: keepPreviousData,
  });
}

/** Отклики всех загруженных страниц подряд. */
export function myResponseItems(pages: Pick<MyResponsesPages, 'pages'> | undefined) {
  return pages?.pages.flatMap((page) => page.items) ?? [];
}

/** Свой отклик для правки S16; `null` — запрашивать нечего. */
export function useMyResponse(responseId: string | null) {
  return useQuery({
    queryKey: getJobsGetResponseQueryKey(responseId ?? ''),
    queryFn: ({ signal }) => jobsGetResponse(responseId ?? '', { signal }),
    enabled: responseId !== null,
  });
}

function refresh(client: QueryClient, jobId: string, response?: MyResponseOut): void {
  if (response) client.setQueryData(getJobsGetResponseQueryKey(response.id), response);
  void client.invalidateQueries({ queryKey: jobQueryKey(jobId) });
  void client.invalidateQueries({ queryKey: MY_RESPONSES_KEY });
  void client.invalidateQueries({ queryKey: FEED_KEY });
}

export interface SendResponse {
  jobId: string;
  body: ResponseIn;
  /** Idempotency-Key — ключ формы: повтор той же отправки. */
  key: string;
}

export function useRespond() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ jobId, body, key }: SendResponse) =>
      jobsRespond(jobId, body, { 'Idempotency-Key': key }),
    onSettled: (response, _error, { jobId }) => refresh(client, jobId, response),
  });
}

export interface ReviseResponse {
  jobId: string;
  responseId: string;
  body: ResponseOfferIn;
}

export function useReviseResponse() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ responseId, body }: ReviseResponse) => jobsReviseResponse(responseId, body),
    onSettled: (response, _error, { jobId }) => refresh(client, jobId, response),
  });
}

export interface WithdrawResponse {
  jobId: string;
  responseId: string;
}

export function useWithdrawResponse() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ responseId }: WithdrawResponse) => jobsWithdrawResponse(responseId),
    onSettled: (response, _error, { jobId }) => refresh(client, jobId, response),
  });
}
