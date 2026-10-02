// Параметры адреса S05 → запрос выдачи (API 4.2). Цена — из RSD в пара, «До 3 км» и «Ближе» —
// только с точкой клиента: без неё сервер ответил бы 422.
import type { SpecialistQuery } from '@sosed/hooks';
import { rsdToPara } from '@sosed/domain';

import type { ResultsSearch } from './paths.ts';

export function toQuery(search: ResultsSearch, cityId: number): SpecialistQuery {
  const point = search.lat !== undefined && search.lon !== undefined;
  return {
    city_id: cityId,
    q: search.q,
    sort: search.sort === 'distance' && !point ? undefined : search.sort,
    category_id: search.category,
    district_ids: search.districts,
    price_max: search.price !== undefined ? rsdToPara(search.price) : undefined,
    languages: search.langs,
    work_modes: search.modes,
    available_today: search.today,
    with_reviews: search.reviews,
    radius_km: point ? search.near : undefined,
    lat: point ? search.lat : undefined,
    lon: point ? search.lon : undefined,
    kind: search.kind,
    urgent: search.urgent,
  };
}

/** Сколько фильтров выбрано — число на чипе «Фильтры». Текст и порядок фильтрами не считаются. */
export function activeFilters(search: ResultsSearch): number {
  return [
    search.category !== undefined,
    (search.districts?.length ?? 0) > 0,
    search.price !== undefined,
    (search.langs?.length ?? 0) > 0,
    (search.modes?.length ?? 0) > 0,
    search.today === true,
    search.reviews === true,
    search.near !== undefined,
  ].filter(Boolean).length;
}

/** «Сбросить фильтры»: остаются текст запроса и вид специалистов. */
export function withoutFilters(search: ResultsSearch): ResultsSearch {
  return { q: search.q, kind: search.kind };
}
