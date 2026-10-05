// Свой профиль исполнителя (DEVELOPMENT_PLAN 2.9, API 2.8a–b): GET /me/profile, где 404
// `profile_not_found` — «профиля ещё нет» (null), а не ошибка экрана. Отсюда же — шаг мастера
// S32a–c, с которого продолжить черновик, и состояние профиля для S31.
import type { NotificationOut, ProfileOut, ProfileStatus } from '@sosed/api-client';
import {
  ApiError,
  getSpecialistsGetMyProfileQueryKey,
  specialistsGetMyProfile,
} from '@sosed/api-client';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect } from 'react';

import { OWN_STALE_MS } from '../cache.ts';

/** Шаги мастера «Стать специалистом»: тип (S32a), о себе (S32b), районы и цены (S32c). */
export const BECOME_STEPS = ['type', 'about', 'area'] as const;
export type BecomeStep = (typeof BECOME_STEPS)[number];

/** Поле из `missing` профиля → шаг мастера, где его заполняют. */
const STEP_OF: Readonly<Record<string, BecomeStep>> = {
  category_ids: 'about',
  headline: 'about',
  work_modes: 'area',
  area_ids: 'area',
  services: 'area',
};

/** Свой профиль или null. Префикс — ключ GET /me/profile: его инвалидации доходят и сюда. */
export function myProfileQueryKey() {
  return [...getSpecialistsGetMyProfileQueryKey(), 'own'] as const;
}

/** Пока профиль на проверке, перечитываем его: 5, 10, 20, 40 с, дальше раз в минуту. Решение
 *  модератора приходит без участия экрана — иначе S31/S33 до перезапуска показывали «На проверке»
 *  уже опубликованного профиля (SMOKE-4). */
export function pendingProfilePollMs(fetches: number): number {
  return Math.min(60_000, 5_000 * 2 ** Math.max(0, fetches - 1));
}

export function useMyProfile({ enabled = true }: { enabled?: boolean } = {}) {
  return useQuery({
    queryKey: myProfileQueryKey(),
    queryFn: async ({ signal }): Promise<ProfileOut | null> => {
      try {
        return await specialistsGetMyProfile({ signal });
      } catch (error) {
        if (error instanceof ApiError && error.status === 404) return null;
        throw error;
      }
    },
    enabled,
    staleTime: OWN_STALE_MS,
    refetchInterval: (query) =>
      query.state.data?.status === 'pending_review'
        ? pendingProfilePollMs(query.state.dataUpdateCount)
        : false,
    // вернулись в Mini App — на проверке профиль перечитываем сразу, а не через 5 минут свежести
    refetchOnWindowFocus: (query) =>
      query.state.data?.status === 'pending_review' ? 'always' : true,
  });
}

/** Решения модерации, после которых профиль «на проверке» уже не на проверке. */
const PROFILE_DECISIONS: ReadonlySet<NotificationOut['type']> = new Set([
  'profile.published',
  'moderation.decision',
]);

/** Лента уведомлений (S42) показала решение модерации, а свой профиль в кэше ещё «на проверке» —
 *  перечитать: S31/S33 сразу согласны с уведомлением. */
export function useProfileDecisions(items: readonly Pick<NotificationOut, 'type'>[]): void {
  const queryClient = useQueryClient();
  const decided = items.some((item) => PROFILE_DECISIONS.has(item.type));
  useEffect(() => {
    if (!decided) return;
    const profile = queryClient.getQueryData<ProfileOut | null>(myProfileQueryKey());
    if (profile?.status === 'pending_review') {
      void queryClient.invalidateQueries({ queryKey: myProfileQueryKey() });
    }
  }, [decided, queryClient]);
}

/**
 * С какого шага продолжить мастер: без профиля — с выбора типа; у черновика — с первого шага, где
 * чего-то не хватает, а если всё заполнено — с последнего, где «Отправить на проверку». Профиль
 * уже отправлен или опубликован — мастер пройден: null.
 */
export function becomeStep(
  profile: Pick<ProfileOut, 'status' | 'missing'> | null,
): BecomeStep | null {
  if (!profile) return 'type';
  if (profile.status !== 'draft') return null;
  const steps = new Set(profile.missing.map((field) => STEP_OF[field] ?? 'area'));
  return BECOME_STEPS.find((step) => steps.has(step)) ?? 'area';
}

/** Состояние профиля для человека: черновик после отказа модерации — «нужны правки». */
export type ProfileState = ProfileStatus | 'rejected';

export function profileState(
  profile: Pick<ProfileOut, 'status' | 'rejection_reason'>,
): ProfileState {
  return profile.status === 'draft' && profile.rejection_reason ? 'rejected' : profile.status;
}
