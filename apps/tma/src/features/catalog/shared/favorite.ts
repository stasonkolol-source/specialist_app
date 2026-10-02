// Сердечко «в избранное» на карточках S05, S12 и в шапке S08 (DEVELOPMENT_PLAN 4.6): состояние —
// из одного списка избранного (packages/hooks), нажатие меняет его сразу. Гостю сердечка нет.
// Ошибка сохранения — текстом над списком; «больше 100» — со своим текстом.
import type { SpecialistCardOut } from '@sosed/api-client';
import { ApiError } from '@sosed/api-client';
import { favoriteIds, useFavorites, useToggleFavorite } from '@sosed/hooks';
import { useLocale, useTranslation } from '@sosed/i18n';
import { usePlatform } from '@sosed/platform';

const FULL = 'favorites_full';

export interface FavoriteControl {
  label: string;
  active: boolean;
  onToggle: () => void;
}

export function useFavoriteToggle() {
  const { t } = useTranslation('catalog');
  const locale = useLocale();
  const platform = usePlatform();
  const favorites = useFavorites(locale);
  const toggle = useToggleFavorite(locale);
  const ids = favoriteIds(favorites.data);
  /** Сердечко карточки; undefined — гость или список ещё не загружен. */
  const control = (card: SpecialistCardOut, named = true): FavoriteControl | undefined => {
    if (!favorites.data) return undefined;
    const active = ids.has(card.profile_id);
    const name = card.display_name;
    return {
      active,
      label: named
        ? t(active ? 'favorites.removeNamed' : 'favorites.addNamed', { name })
        : t(active ? 'favorites.remove' : 'favorites.add'),
      onToggle: () => {
        platform.haptics.selection();
        toggle.mutate({ card, on: !active });
      },
    };
  };
  const error = toggle.error;
  const failure = !toggle.isError
    ? null
    : error instanceof ApiError && error.code === FULL
      ? t('favorites.full', { limit: Number(error.problem['limit'] ?? 100) })
      : t('favorites.error');
  return { control, failure, favorites };
}
