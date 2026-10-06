// Сделки (S24–S26, S53; DEVELOPMENT_PLAN 6.2, 6.5): выбрать отклик исполнителем — сделка создаётся
// сразу; карточка сделки сторонам (BFF), «Работа выполнена», отмена с причиной, свои сделки;
// «Договорились» из чата — подтвердить или отклонить. После действия перечитываются сделка,
// отклики заявки, свои заявки и отклики, а после ответа на предложение — и переписка. Ждёт экран
// только то, что показывает сам (карточку сделки S26); остальное — в фоне. Заявку из ответа
// сервера (принять, отклонить) кладём в кэш и не перечитываем.
import type {
  AcceptedOut,
  DealCancelReason,
  DealCardOut,
  DealsListMyDealsParams,
  ResponseCardOut,
} from '@sosed/api-client';
import {
  ApiError,
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
  jobsGetJob,
  viewsGetDealCard,
} from '@sosed/api-client';
import type { QueryClient } from '@tanstack/react-query';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useRef } from 'react';

import { FEED_KEY } from '../jobs/feed.ts';
import { jobQueryKey } from '../jobs/jobs.ts';
import { RESPONSES_POLL_MS, myJobsQueryKey, responseCardsQueryKey } from '../jobs/mine.ts';
import { MY_RESPONSES_KEY } from '../jobs/responses.ts';
import { refreshInbox } from '../messages/conversations.ts';

export const dealCardQueryKey = (dealId: string) => getViewsGetDealCardQueryKey(dealId);
/** Префикс всех списков `GET /me/deals`: после действия перечитываются все. */
export const MY_DEALS_KEY = getDealsListMyDealsQueryKey().slice(0, 1);

/** Сделка идёт: вторая сторона может подтвердить, отметить «Работа выполнена», отменить или
 *  ответить на спор. */
const LIVE_DEAL: ReadonlySet<DealCardOut['status']> = new Set(['proposed', 'agreed', 'disputed']);
const isLive = (deal: DealCardOut | undefined) => deal !== undefined && LIVE_DEAL.has(deal.status);
/** Свой отзыв ещё на проверке: автопроверка публикует чистый за секунды — перечитываем часто, но
 *  не дольше 30 с, дальше экран честно пишет «обычно несколько минут» (UX_GUIDANCE №1). */
export const REVIEW_SETTLE_POLL_MS = 2_500;
export const REVIEW_SETTLE_MS = 30_000;

/** Сделка стороне (S26): условия, вторая сторона, место и вехи. `live` — экран ждёт вторую
 *  сторону (QA MU-4): пока сделка идёт, карточка опрашивается в темпе откликов S23 и
 *  перечитывается, когда Mini App снова на экране (без этого «Договорились» висело и после
 *  завершения второй стороной). Свой отзыв на проверке — тоже ждём, пока не опубликуют (до 30 с
 *  с того, как экран его увидел): на S26 и S27 — настоящий статус, а не вечное «на проверке». */
export function useDealCard(dealId: string | null, { live = false }: { live?: boolean } = {}) {
  const settling = useRef<number | null>(null);
  return useQuery({
    queryKey: dealCardQueryKey(dealId ?? ''),
    queryFn: ({ signal }) => viewsGetDealCard(dealId ?? '', { signal }),
    enabled: dealId !== null,
    refetchInterval: (query) => {
      const deal = query.state.data;
      if (!live) return false;
      if (isLive(deal)) return RESPONSES_POLL_MS;
      if (deal?.my_review?.status !== 'under_review') {
        settling.current = null;
        return false;
      }
      settling.current ??= Date.now();
      return Date.now() - settling.current < REVIEW_SETTLE_MS ? REVIEW_SETTLE_POLL_MS : false;
    },
    refetchOnWindowFocus: (query) => (live && isLive(query.state.data) ? 'always' : false),
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

/** Списки после действия — в фоне. `seeded` — заявка уже из ответа сервера: её не перечитываем. */
function refresh(client: QueryClient, jobId: string | null, seeded = false): void {
  void client.invalidateQueries({ queryKey: MY_DEALS_KEY });
  void client.invalidateQueries({ queryKey: myJobsQueryKey() });
  void client.invalidateQueries({ queryKey: MY_RESPONSES_KEY });
  void client.invalidateQueries({ queryKey: FEED_KEY });
  if (!jobId) return;
  if (!seeded) void client.invalidateQueries({ queryKey: jobQueryKey(jobId) });
  void client.invalidateQueries({ queryKey: responseCardsQueryKey(jobId) });
}

export interface DecideResponse {
  jobId: string;
  responseId: string;
  /** Редакция предложения, которую клиент видел (`revision` карточки отклика): If-Match выбора —
   *  исполнитель успел поправить цену, и сервер ответит 409 `offer_changed` (QA ADV-08). */
  revision?: number;
}

/** Исполнитель поправил предложение, пока клиент его выбирал: в ответе — нынешние условия. */
export const OFFER_CHANGED = 'offer_changed';

/** Нынешнее предложение из 409 `offer_changed`: редакция для нового If-Match и цена. */
export interface ChangedOffer {
  revision: number;
  price_type: ResponseCardOut['price']['type'];
  price_amount: number | null;
}

export function changedOffer(error: unknown): ChangedOffer | null {
  if (!(error instanceof ApiError) || error.code !== OFFER_CHANGED) return null;
  const { revision, price_type: type, price_amount: amount } = error.problem;
  if (typeof revision !== 'number' || typeof type !== 'string') return null;
  return {
    revision,
    price_type: type as ChangedOffer['price_type'],
    price_amount: typeof amount === 'number' ? amount : null,
  };
}

/** «Выбрать исполнителем» (S25): ответ — id сделки и заявка «в работе». Повтор того же выбора
 *  (второй запрос двойного тапа, повтор после обрыва) сервер отвергает 409 — заявка уже «в
 *  работе»; если в работе она именно с этим откликом, выбор состоялся: это успех, а не ошибка
 *  (QA MU-5), сделка — из своих сделок. С редакцией — If-Match: предложение поменялось — 409
 *  `offer_changed`, сделки нет, отклики заявки перечитываются с новой ценой. */
export function useAcceptResponse() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async ({ jobId, responseId, revision }: DecideResponse): Promise<AcceptedOut> => {
      try {
        const ifMatch = revision === undefined ? undefined : { 'If-Match': `"${revision}"` };
        return await jobsAcceptResponse(responseId, ifMatch);
      } catch (error) {
        const earlier =
          error instanceof ApiError && error.status === 409 && error.code !== OFFER_CHANGED
            ? await acceptedEarlier(jobId, responseId)
            : null;
        if (!earlier) throw error;
        return earlier;
      }
    },
    // сделку S26 открываем по ответу сервера, не дожидаясь перечитывания списков
    onSuccess: (accepted, { jobId }) => {
      client.setQueryData(jobQueryKey(jobId), accepted.job);
      refresh(client, jobId, true);
    },
    onError: (error, { jobId }) => {
      if (changedOffer(error)) {
        void client.invalidateQueries({ queryKey: responseCardsQueryKey(jobId) });
      }
    },
  });
}

/** Отклик уже выбран: идущая сделка по нему и заявка. Нет такой сделки — `null`, ошибка в силе. */
async function acceptedEarlier(jobId: string, responseId: string): Promise<AcceptedOut | null> {
  const deals = await dealsListMyDeals({ role: 'client' });
  const deal = deals.items.find(
    (item) => item.response_id === responseId && item.status !== 'cancelled',
  );
  return deal ? { deal_id: deal.id, job: await jobsGetJob(jobId) } : null;
}

/** «Отклонить» (S24): место на заявке освобождается. */
export function useDeclineResponse() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ responseId }: DecideResponse) => jobsDeclineResponse(responseId),
    onSuccess: (job, { jobId }) => {
      client.setQueryData(jobQueryKey(jobId), job);
      refresh(client, jobId, true);
    },
  });
}

/** «Работа выполнена» (S26): отметка стороны; отметили обе — сделка завершена. */
export function useCompleteDeal() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (dealId: string) => dealsCompleteDeal(dealId),
    // человек остаётся на S26: ждём только её карточку
    onSuccess: async (deal) => {
      refresh(client, deal.job_id ?? null);
      await client.invalidateQueries({ queryKey: dealCardQueryKey(deal.id) });
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
      refresh(client, deal.job_id ?? null);
      await client.invalidateQueries({ queryKey: dealCardQueryKey(deal.id) });
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
      refresh(client, deal.job_id ?? null);
      void refreshInbox(client);
      await client.invalidateQueries({ queryKey: dealCardQueryKey(deal.id) });
    },
  });
}
