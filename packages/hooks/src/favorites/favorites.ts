// Избранное (DEVELOPMENT_PLAN 4.6): «мои мастера» S12 и сердечко на S05 и S08 — из одного списка
// GET /me/favorites, поэтому экраны не расходятся. Нажатие сразу меняет список (оптимистично),
// ошибка возвращает как было, после ответа список перечитывается. Карточки — на языке запроса:
// язык — часть ключа. Гостю избранного нет: без сессии запроса нет.
import type {
  FavoritesOut,
  Locale,
  SpecialistCardOut,
  SpecialistProfileOut,
} from '@sosed/api-client';
import {
  getSearchListFavoritesQueryKey,
  getSession,
  searchAddFavorite,
  searchListFavorites,
  searchRemoveFavorite,
} from '@sosed/api-client';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

export function favoritesQueryKey(locale: Locale) {
  return [...getSearchListFavoritesQueryKey(), locale] as const;
}

export function useFavorites(locale: Locale) {
  return useQuery({
    queryKey: favoritesQueryKey(locale),
    queryFn: ({ signal }) => searchListFavorites({ signal }),
    enabled: getSession() !== null,
  });
}

/** id специалистов в избранном — для сердечек S05 и S08. */
export function favoriteIds(out: FavoritesOut | undefined): ReadonlySet<string> {
  return new Set(out?.items.map((item) => item.profile_id) ?? []);
}

export interface FavoriteToggle {
  /** Карточка — встать в начало списка S12 до ответа сервера. */
  card: SpecialistCardOut;
  on: boolean;
}

export function useToggleFavorite(locale: Locale) {
  const client = useQueryClient();
  const key = favoritesQueryKey(locale);
  return useMutation({
    mutationFn: ({ card, on }: FavoriteToggle) =>
      on ? searchAddFavorite(card.profile_id) : searchRemoveFavorite(card.profile_id),
    onMutate: async ({ card, on }) => {
      await client.cancelQueries({ queryKey: key });
      const before = client.getQueryData<FavoritesOut>(key);
      client.setQueryData<FavoritesOut>(key, (old) => {
        const items = (old?.items ?? []).filter((item) => item.profile_id !== card.profile_id);
        return { items: on ? [card, ...items] : items };
      });
      return { before };
    },
    onError: (_error, { card }, context) => {
      if (!context) return;
      client.setQueryData<FavoritesOut>(key, (old) => {
        if (!old) return old;
        // Откатываем только эту карточку: соседние сохранения могли уже завершиться.
        const items = old.items.filter((item) => item.profile_id !== card.profile_id);
        const index =
          context.before?.items.findIndex((item) => item.profile_id === card.profile_id) ?? -1;
        const previous = context.before?.items[index];
        if (previous) items.splice(index, 0, previous);
        return { items };
      });
    },
    // список уже поправлен оптимистично: сверка с сервером — в фоне
    onSettled: () => void client.invalidateQueries({ queryKey: getSearchListFavoritesQueryKey() }),
  });
}

/** Карточка S08 как карточка выдачи — для списка S12 до ответа сервера. Цену «от» и расстояние
 *  профиль не знает: их подставит перечитанный список. */
export function searchCardOf(profile: SpecialistProfileOut): SpecialistCardOut {
  const variant = profile.avatar?.variants.find((v) => v.name === 'thumb') ?? null;
  return {
    profile_id: profile.id,
    display_name: profile.display_name,
    headline: profile.headline,
    kind: profile.kind,
    avatar:
      variant && profile.avatar
        ? {
            url: variant.url,
            width: variant.width,
            height: variant.height,
            placeholder: profile.avatar.placeholder,
          }
        : null,
    district: profile.district,
    distance_m: null,
    languages: profile.languages,
    category_ids: profile.categories.map((category) => category.id),
    price_from: null,
    negotiable: false,
    rating: profile.rating,
    rating_count: profile.rating_count,
    is_new: profile.is_new,
    available_until: profile.available_until,
    badges: profile.badges,
  };
}
