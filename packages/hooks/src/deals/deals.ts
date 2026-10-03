// Сделки (S24–S26, S53; DEVELOPMENT_PLAN 6.2, 6.5): выбрать отклик исполнителем — сделка создаётся
// сразу; карточка сделки сторонам (BFF), «Работа выполнена», отмена с причиной, свои сделки;
// «Договорились» из чата — подтвердить или отклонить. После действия перечитываются сделка,
// отклики заявки, свои заявки и отклики, а после ответа на предложение — и переписка.
import type { DealCancelReason, DealsListMyDealsParams } from '@sosed/api-client';
import {
  dealsCancelDeal,
  dealsCompleteDeal,
  dealsConfirmDeal,
  dealsDeclineDeal,
  dealsListMyDeals,
  getDealsListMyDealsQueryKey,
  getSession,
  getViewsGetDealCardQueryKey,
  jobsAcceptResponse,
  jobsDeclineResponse,
  viewsGetDealCard,
} from '@sosed/api-client';
import type { QueryClient } from '@tanstack/react-query';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { FEED_KEY } from '../jobs/feed.ts';
import { jobQueryKey } from '../jobs/jobs.ts';
import { myJobsQueryKey, responseCardsQueryKey } from '../jobs/mine.ts';
import { MY_RESPONSES_KEY } from '../jobs/responses.ts';
import { refreshInbox } from '../messages/conversations.ts';

export const dealCardQueryKey = (dealId: string) => getViewsGetDealCardQueryKey(dealId);
/** Префикс всех списков `GET /me/deals`: после действия перечитываются все. */
export const MY_DEALS_KEY = getDealsListMyDealsQueryKey().slice(0, 1);

/** Сделка стороне (S26): условия, вторая сторона, место и вехи. */
export function useDealCard(dealId: string | null) {
  return useQuery({
    queryKey: dealCardQueryKey(dealId ?? ''),
    queryFn: ({ signal }) => viewsGetDealCard(dealId ?? '', { signal }),
    enabled: dealId !== null,
  });
}

/** Свои сделки (`role` — клиентом или исполнителем): ссылка «Открыть сделку» на S23 и S17. */
export function useMyDeals(params: DealsListMyDealsParams) {
  return useQuery({
    queryKey: getDealsListMyDealsQueryKey(params),
    queryFn: ({ signal }) => dealsListMyDeals(params, { signal }),
    enabled: getSession() !== null,
  });
}

async function refresh(client: QueryClient, jobId: string | null) {
  await Promise.all([
    client.invalidateQueries({ queryKey: MY_DEALS_KEY }),
    client.invalidateQueries({ queryKey: myJobsQueryKey() }),
    client.invalidateQueries({ queryKey: MY_RESPONSES_KEY }),
    client.invalidateQueries({ queryKey: FEED_KEY }),
    ...(jobId
      ? [
          client.invalidateQueries({ queryKey: jobQueryKey(jobId) }),
          client.invalidateQueries({ queryKey: responseCardsQueryKey(jobId) }),
        ]
      : []),
  ]);
}

export interface DecideResponse {
  jobId: string;
  responseId: string;
}

/** «Выбрать исполнителем» (S25): ответ — id сделки и заявка «в работе». */
export function useAcceptResponse() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ responseId }: DecideResponse) => jobsAcceptResponse(responseId),
    onSuccess: async (accepted, { jobId }) => {
      client.setQueryData(jobQueryKey(jobId), accepted.job);
      await refresh(client, jobId);
    },
  });
}

/** «Отклонить» (S24): место на заявке освобождается. */
export function useDeclineResponse() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ responseId }: DecideResponse) => jobsDeclineResponse(responseId),
    onSuccess: async (job, { jobId }) => {
      client.setQueryData(jobQueryKey(jobId), job);
      await refresh(client, jobId);
    },
  });
}

/** «Работа выполнена» (S26): отметка стороны; отметили обе — сделка завершена. */
export function useCompleteDeal() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (dealId: string) => dealsCompleteDeal(dealId),
    onSuccess: async (deal) => {
      await Promise.all([
        client.invalidateQueries({ queryKey: dealCardQueryKey(deal.id) }),
        refresh(client, deal.job_id ?? null),
      ]);
    },
  });
}

export interface CancelDeal {
  dealId: string;
  reason: DealCancelReason;
}

/** Отменить сделку с причиной (S26): заявка снова открыта, прежние кандидаты ждут решения. */
export function useCancelDeal() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ dealId, reason }: CancelDeal) => dealsCancelDeal(dealId, { reason }),
    onSuccess: async (deal) => {
      await Promise.all([
        client.invalidateQueries({ queryKey: dealCardQueryKey(deal.id) }),
        refresh(client, deal.job_id ?? null),
      ]);
    },
  });
}

/** S53: подтвердить «Договорились» — сделка `agreed`; отклонить — предложение отменяется. */
export function useAnswerProposal() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ dealId, confirm }: { dealId: string; confirm: boolean }) =>
      confirm ? dealsConfirmDeal(dealId) : dealsDeclineDeal(dealId),
    onSuccess: async (deal) => {
      await Promise.all([
        client.invalidateQueries({ queryKey: dealCardQueryKey(deal.id) }),
        refresh(client, deal.job_id ?? null),
        refreshInbox(client),
      ]);
    },
  });
}
