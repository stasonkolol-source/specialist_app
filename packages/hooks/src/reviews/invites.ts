// «Отзывы до платформы» (S55, S56; DEVELOPMENT_PLAN 7.6а): специалист создаёт ссылки прошлым
// клиентам (мест пять: ждущая отзыва и использованная ссылка место занимают) и отзывает
// неиспользованные; клиент по ссылке `ri_` видит, кто просит отзыв, и оставляет его — отзыв ждёт
// модератора, на карточке он с отдельной меткой и в рейтинг не входит.
import type { InviteReviewIn, ReviewInviteIn, ReviewInvitesOut } from '@sosed/api-client';
import {
  getReviewsListReviewInvitesQueryKey,
  getSession,
  getViewsGetReviewInviteQueryKey,
  reviewsCreateReviewInvite,
  reviewsLeaveInviteReview,
  reviewsListReviewInvites,
  reviewsRevokeReviewInvite,
  viewsGetReviewInvite,
} from '@sosed/api-client';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { MY_REVIEWS_KEY } from './reviews.ts';

/** Мест под приглашения — `limit` backend; ответ его не прислал — пять, как в правилах S55. */
export const REVIEW_INVITES_LIMIT = 5;
/** «Кому» — заметка специалиста в списке S55, как `client_name` backend. */
export const INVITE_NAME_MAX = 60;
/** «Что делал мастер» и текст отзыва S56 — как `work_title` и `body` backend. */
export const INVITE_WORK_MAX = 120;
export const INVITE_BODY_MAX = 2000;

export const reviewInvitesQueryKey = () => getReviewsListReviewInvitesQueryKey();

/** Приглашения S55 и «2 из 5» в строке кабинета S33; гостю списка нет. */
export function useReviewInvites({ enabled = true }: { enabled?: boolean } = {}) {
  return useQuery({
    queryKey: reviewInvitesQueryKey(),
    queryFn: ({ signal }) => reviewsListReviewInvites({ signal }),
    enabled: enabled && getSession() !== null,
  });
}

/** «Создать ссылку»: новая — первой в списке и занимает место сразу, список перечитывается. Отказ
 *  (мест нет, профиль сняли с публикации) — тоже: список на экране мог устареть. */
export function useCreateReviewInvite() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: ReviewInviteIn) => reviewsCreateReviewInvite(body),
    onSuccess: (invite) => {
      client.setQueryData<ReviewInvitesOut>(reviewInvitesQueryKey(), (list) =>
        list ? { ...list, items: [invite, ...list.items], taken: list.taken + 1 } : list,
      );
      void client.invalidateQueries({ queryKey: reviewInvitesQueryKey() });
    },
    onError: () => void client.invalidateQueries({ queryKey: reviewInvitesQueryKey() }),
  });
}

/** «Отозвать» неиспользованную ссылку: она перестаёт открываться, место освобождается. Отказ
 *  (по ссылке как раз оставили отзыв) — список перечитывается со свежим статусом. */
export function useRevokeReviewInvite() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (token: string) => reviewsRevokeReviewInvite(token),
    onError: () => void client.invalidateQueries({ queryKey: reviewInvitesQueryKey() }),
    onSuccess: (_, token) => {
      client.setQueryData<ReviewInvitesOut>(reviewInvitesQueryKey(), (list) =>
        list
          ? {
              ...list,
              items: list.items.filter((invite) => invite.token !== token),
              taken: Math.max(0, list.taken - 1),
            }
          : list,
      );
      void client.invalidateQueries({ queryKey: reviewInvitesQueryKey() });
    },
  });
}

/** Форма S56: кто просит отзыв. Ссылка отозвана, истекла, использована или её нет — 404. */
export function useReviewInvite(token: string | null) {
  return useQuery({
    queryKey: getViewsGetReviewInviteQueryKey(token ?? ''),
    queryFn: ({ signal }) => viewsGetReviewInvite(token ?? '', { signal }),
    enabled: token !== null,
  });
}

/** Отзыв по ссылке S56: ждёт модератора; «Мои отзывы» S28 перечитываются. */
export function useLeaveInviteReview(token: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: InviteReviewIn) => reviewsLeaveInviteReview(token, body),
    onSuccess: () => void client.invalidateQueries({ queryKey: MY_REVIEWS_KEY }),
  });
}
