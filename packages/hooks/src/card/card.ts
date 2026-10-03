// Карточка специалиста S08–S10 (DEVELOPMENT_PLAN 4.5): профиль одним запросом BFF, прайс и
// портфолио. Названия категорий и районов приходят на языке запроса (Accept-Language), поэтому
// язык — часть ключа профиля и прайса; подписи работ пишет специалист — их ключ без языка.
// 404 — профиль скрыт, снят или его нет: экран говорит «недоступен», а не «ошибка».
import type {
  CardNamedOut,
  CardPhotoOut,
  CardServiceOut,
  CardServicesOut,
  Locale,
} from '@sosed/api-client';
import {
  ApiError,
  getViewsGetSpecialistQueryKey,
  getViewsListSpecialistReviewsQueryKey,
  getViewsListSpecialistServicesQueryKey,
  getViewsListSpecialistWorksQueryKey,
  useViewsGetSpecialist,
  useViewsListSpecialistServices,
  useViewsListSpecialistWorks,
  viewsListSpecialistReviews,
} from '@sosed/api-client';
import { useInfiniteQuery } from '@tanstack/react-query';

/** Как Cache-Control ответов (max-age=60). */
export const CARD_STALE_MS = 60_000;

export function specialistCardQueryKey(profileId: string, locale: Locale) {
  return [...getViewsGetSpecialistQueryKey(profileId), locale] as const;
}

export function specialistServicesQueryKey(profileId: string, locale: Locale) {
  return [...getViewsListSpecialistServicesQueryKey(profileId), locale] as const;
}

/** S08: профиль, первые позиции прайса и превью работ; `null` — карточка не нужна (мастер заявки
 *  без прямого запроса). */
export function useSpecialistCard(profileId: string | null, locale: Locale) {
  return useViewsGetSpecialist(profileId ?? '', {
    query: {
      queryKey: specialistCardQueryKey(profileId ?? '', locale),
      staleTime: CARD_STALE_MS,
      enabled: profileId !== null,
    },
  });
}

/** S09: весь прайс и его группы. */
export function useSpecialistServices(profileId: string, locale: Locale) {
  return useViewsListSpecialistServices(profileId, {
    query: { queryKey: specialistServicesQueryKey(profileId, locale), staleTime: CARD_STALE_MS },
  });
}

/** S10: все работы с готовыми файлами. */
export function useSpecialistWorks(profileId: string) {
  return useViewsListSpecialistWorks(profileId, {
    query: { queryKey: getViewsListSpecialistWorksQueryKey(profileId), staleTime: CARD_STALE_MS },
  });
}

export const SPECIALIST_REVIEWS_PAGE = 20;

/** S11: рейтинг с гистограммой (первая страница) и отзывы страницами «Показать ещё»; услуги в
 * отзывах — на языке запроса. */
export function useSpecialistReviews(profileId: string, locale: Locale) {
  return useInfiniteQuery({
    queryKey: [...getViewsListSpecialistReviewsQueryKey(profileId), locale] as const,
    queryFn: ({ pageParam, signal }) =>
      viewsListSpecialistReviews(
        profileId,
        { limit: SPECIALIST_REVIEWS_PAGE, ...(pageParam ? { cursor: pageParam } : {}) },
        { signal },
      ),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor ?? null,
    staleTime: CARD_STALE_MS,
  });
}

/** Профиль скрыт, снят санкцией или его нет (404), либо ссылка битая (422). */
export function isUnavailable(error: unknown): boolean {
  return error instanceof ApiError && (error.status === 404 || error.status === 422);
}

export interface PriceGroup {
  /** null — позиции без группы (или их категорию убрали из каталога). */
  category: CardNamedOut | null;
  items: CardServiceOut[];
}

/** Группы прайса S09 в порядке позиций; позиции без группы — в конце. */
export function priceGroups(out: CardServicesOut): PriceGroup[] {
  const known = new Set(out.categories.map((category) => category.id));
  const groups: PriceGroup[] = out.categories.map((category) => ({
    category,
    items: out.items.filter((service) => service.category_id === category.id),
  }));
  groups.push({
    category: null,
    items: out.items.filter(
      (service) => service.category_id === null || !known.has(service.category_id),
    ),
  });
  return groups.filter((group) => group.items.length > 0);
}

/** Варианты фото для `Photo` (srcset): thumb 320, md 800, lg 1600. */
export function cardVariants(photo: CardPhotoOut): { url: string; width: number }[] {
  return photo.variants.map((variant) => ({ url: variant.url, width: variant.width }));
}

/** Самый крупный вариант: постер ролика и фото в просмотрщике без srcset. */
export function largestVariant(photo: CardPhotoOut) {
  return photo.variants.reduce<CardPhotoOut['variants'][number] | undefined>(
    (best, variant) => (best === undefined || variant.width > best.width ? variant : best),
    undefined,
  );
}
