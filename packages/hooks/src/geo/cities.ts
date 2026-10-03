// Города для выбора (онбординг S02a, позже настройки): GET /cities — активные и «скоро».
// Названия приходят на языке запроса (Accept-Language), поэтому язык — часть ключа: после смены
// языка без перезагрузки список перечитывается, а до ответа виден прежний (без скелетона).
import type { CityOut, Locale } from '@sosed/api-client';
import { getGeoListCitiesQueryKey, getGeoListCitiesQueryOptions } from '@sosed/api-client';
import { keepPreviousData, useQuery } from '@tanstack/react-query';

/** Справочник меняется редко: час без перечитывания (ответ сервера кэшируется на 5 минут —
 *  Cache-Control max-age=300). */
export const CITIES_STALE_MS = 60 * 60_000;

export function citiesQueryKey(locale: Locale) {
  return [...getGeoListCitiesQueryKey(), locale] as const;
}

/** Ключ и свежесть — одни у хука и у предзагрузки при запуске: запрос не задвоится. */
export function citiesQueryOptions(locale: Locale) {
  return getGeoListCitiesQueryOptions({
    query: { queryKey: citiesQueryKey(locale), staleTime: CITIES_STALE_MS },
  });
}

export function useCities(locale: Locale) {
  return useQuery({ ...citiesQueryOptions(locale), placeholderData: keepPreviousData });
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
