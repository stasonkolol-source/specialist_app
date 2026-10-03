// Город выдачи: свой у вошедшего (home_city_id), иначе — первый открытый (Нови-Сад в пилоте).
// Гость тоже видит каталог (DEVELOPMENT_PLAN 4.4): без /me город — по умолчанию.
import type { CityOut } from '@sosed/api-client';
import { useIdentityGetMe } from '@sosed/api-client';
import { defaultCity, useCities } from '@sosed/hooks';
import { useLocale } from '@sosed/i18n';
import { usePlatform } from '@sosed/platform';

export interface CatalogCity {
  city: CityOut | null;
  /** Город ещё решается — ответа городов или /me нет: место под него держит скелетон. */
  pending: boolean;
}

export function useCatalogCityState(): CatalogCity {
  const locale = useLocale();
  const platform = usePlatform();
  const inTelegram = platform.launch.rawInitData !== null;
  const me = useIdentityGetMe({ query: { enabled: inTelegram } });
  const cities = useCities(locale);
  // вошедший ждёт свой город: иначе выдача загрузилась бы дважды
  if (!cities.data || (inTelegram && me.isPending)) {
    return { city: null, pending: cities.isPending || (inTelegram && me.isPending) };
  }
  const id = defaultCity(cities.data, me.data?.home_city_id ?? null);
  return { city: cities.data.find((city) => city.id === id) ?? null, pending: false };
}

export function useCatalogCity(): CityOut | null {
  return useCatalogCityState().city;
}
