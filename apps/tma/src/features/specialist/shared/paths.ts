// Адреса мастера «Стать специалистом» S32a–c (DEVELOPMENT_PLAN 2.9). S31 открывает первый шаг с
// уже отмеченным типом: «Стать специалистом» — `?kind=pro`, «Найти подработку» — `?kind=casual`.
import type { ProfileKind } from '@sosed/api-client';
import type { BecomeStep } from '@sosed/hooks';

export const BECOME_PATHS = {
  type: '/become/type',
  about: '/become/about',
  area: '/become/area',
} as const satisfies Record<BecomeStep, string>;

/** S31: сюда мастер ведёт после отправки на проверку и «Назад» с первого шага без истории. */
export const ACCOUNT_PATH = '/profile';

export interface BecomeSearch {
  kind?: ProfileKind;
}

/** validateSearch первого шага: тип — только из известных. */
export function becomeSearch(search: Record<string, unknown>): BecomeSearch {
  const { kind } = search;
  return kind === 'pro' || kind === 'casual' ? { kind } : {};
}
