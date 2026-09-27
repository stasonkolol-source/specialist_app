// Города для выбора (онбординг S02a, позже настройки): GET /cities — активные и «скоро».
// Названия приходят на языке запроса (Accept-Language), поэтому язык — часть ключа: после смены
// языка без перезагрузки список перечитывается, а до ответа виден прежний (без скелетона).
import type { CityOut, Locale } from '@sosed/api-client';
import { getGeoListCitiesQueryKey, useGeoListCities } from '@sosed/api-client';
import { keepPreviousData } from '@tanstack/react-query';

/** Как Cache-Control ответа (max-age=300): справочник меняется редко. */
export const CITIES_STALE_MS = 5 * 60_000;

export function citiesQueryKey(locale: Locale) {
  return [...getGeoListCitiesQueryKey(), locale] as const;
}

export function useCities(locale: Locale) {
  return useGeoListCities({
    query: {
      queryKey: citiesQueryKey(locale),
      staleTime: CITIES_STALE_MS,
      placeholderData: keepPreviousData,
    },
  });
}

/** Выбрать можно только активный город; «скоро» виден, но недоступен. */
export function isSelectableCity(city: Pick<CityOut, 'status'>): boolean {
  return city.status === 'active';
}

/** Город по умолчанию: уже выбранный, если он ещё активен, иначе первый активный (пилот). */
export function defaultCity(cities: readonly CityOut[], current: number | null): number | null {
  const active = cities.filter(isSelectableCity);
  return (active.find((city) => city.id === current) ?? active[0])?.id ?? null;
}
