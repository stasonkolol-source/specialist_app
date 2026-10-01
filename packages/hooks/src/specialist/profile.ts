// Свой профиль исполнителя (DEVELOPMENT_PLAN 2.9, API 2.8a–b): GET /me/profile, где 404
// `profile_not_found` — «профиля ещё нет» (null), а не ошибка экрана. Отсюда же — шаг мастера
// S32a–c, с которого продолжить черновик, и состояние профиля для S31.
import type { ProfileOut, ProfileStatus } from '@sosed/api-client';
import {
  ApiError,
  getSpecialistsGetMyProfileQueryKey,
  specialistsGetMyProfile,
} from '@sosed/api-client';
import { useQuery } from '@tanstack/react-query';

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
  });
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
