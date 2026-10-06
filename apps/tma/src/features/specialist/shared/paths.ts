// Адреса мастера «Стать специалистом» S32a–c (DEVELOPMENT_PLAN 2.9). S31 открывает первый шаг с
// уже отмеченным типом: «Стать специалистом» — `?kind=pro`, «Найти подработку» — `?kind=casual`.
import type { ProfileKind } from '@sosed/api-client';
import type { BecomeStep } from '@sosed/hooks';

export const BECOME_PATHS = {
  type: '/become/type',
  about: '/become/about',
  area: '/become/area',
} as const satisfies Record<BecomeStep, string>;

/** S31: сюда мастер ведёт по «Назад» с первого шага без истории (после отправки — кабинет S33). */
export const ACCOUNT_PATH = '/profile';

/** Кабинет S33, правка профиля S34, прайс S35–S36, портфолио S37 и работа, доступность S38
 *  (DEVELOPMENT_PLAN 2.10–2.11), приглашения на «отзыв до платформы» S55 (7.6а). */
export const CABINET_PATHS = {
  home: '/cabinet',
  profile: '/cabinet/profile',
  availability: '/cabinet/availability',
  prices: '/cabinet/prices',
  newPrice: '/cabinet/prices/new',
  price: '/cabinet/prices/$serviceId',
  portfolio: '/cabinet/portfolio',
  work: '/cabinet/portfolio/$itemId',
  reviewInvites: '/cabinet/review-invites',
} as const;

export interface BecomeSearch {
  kind?: ProfileKind;
}

/** validateSearch первого шага: тип — только из известных. */
export function becomeSearch(search: Record<string, unknown>): BecomeSearch {
  const { kind } = search;
  return kind === 'pro' || kind === 'casual' ? { kind } : {};
}
