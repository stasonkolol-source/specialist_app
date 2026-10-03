// Спор по сделке (S52; DEVELOPMENT_PLAN 6.1c, 6.2): открыть (что случилось, описание, фото),
// ответить второй стороной, отозвать открывшим. Ответ сервера — спор той же формы, что в карточке
// сделки: кладём его в карточку вместе со статусом сделки — экран меняется сразу, без
// перечитывания. Списки сделок («Сделки и отзывы», свои сделки) — в фоне.
import type { DealCardOut, DisputeAnswerIn, DisputeIn, DisputeOut } from '@sosed/api-client';
import { dealsOpenDispute, dealsRespondDispute, dealsWithdrawDispute } from '@sosed/api-client';
import type { QueryClient } from '@tanstack/react-query';
import { useMutation, useQueryClient } from '@tanstack/react-query';

import { DEAL_HISTORY_KEY } from '../reviews/reviews.ts';
import { MY_DEALS_KEY, dealCardQueryKey } from './deals.ts';

function seed(client: QueryClient, dispute: DisputeOut): void {
  client.setQueryData<DealCardOut>(dealCardQueryKey(dispute.deal_id), (card) =>
    card ? { ...card, status: dispute.deal_status, dispute } : card,
  );
  void client.invalidateQueries({ queryKey: MY_DEALS_KEY });
  void client.invalidateQueries({ queryKey: DEAL_HISTORY_KEY });
}

/** «Отправить» S52: сделка — `disputed`, второй стороне 48 ч на ответ. */
export function useOpenDispute(dealId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: DisputeIn) => dealsOpenDispute(dealId, body),
    onSuccess: (dispute) => seed(client, dispute),
  });
}

/** «Ответить» второй стороны S52: один раз, пока модератор не решил. */
export function useRespondDispute(dealId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: DisputeAnswerIn) => dealsRespondDispute(dealId, body),
    onSuccess: (dispute) => seed(client, dispute),
  });
}

/** «Отозвать спор» открывшим: сделка снова идёт. */
export function useWithdrawDispute(dealId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => dealsWithdrawDispute(dealId),
    onSuccess: (dispute) => seed(client, dispute),
  });
}
