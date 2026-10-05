// Район под меткой карты S20b: backend по границам районов (GET /geo/districts/locate), когда карта
// постояла SETTLE_MS — не на каждый кадр перетаскивания. Ответы — в кэше запросов: вернулся к тому же
// месту — район сразу. 404 `outside_city` — точка за городом. Кэш только в памяти: публичные
// справочники сохраняет persist.ts по белому списку, точек в нём нет.
import type { DistrictOut, PointOut } from '@sosed/api-client';
import { ApiError, geoLocateDistrict } from '@sosed/api-client';
import { useLocale } from '@sosed/i18n';
import { useQuery } from '@tanstack/react-query';

import { useDebounced } from '../../shared/debounce.ts';

export const SETTLE_MS = 400;
/** 4 знака — около 10 м: у границы районов метка не «перескакивает», а точнее точка не уходит. */
const DIGITS = 4;

export type CentreDistrict =
  | { kind: 'pending' }
  | { kind: 'found'; district: DistrictOut }
  | { kind: 'outside' }
  | { kind: 'failed'; retry: () => void };

const round = (value: number) => Number(value.toFixed(DIGITS));

export function useCentreDistrict(
  cityId: number,
  centre: PointOut,
  districts: readonly DistrictOut[],
): CentreDistrict & { point: PointOut } {
  const locale = useLocale();
  const point = { lat: round(centre.lat), lon: round(centre.lon) };
  // строка, а не объект: новый объект на каждом рендере перезапускал бы таймер без конца
  const key = `${point.lat},${point.lon}`;
  const settledKey = useDebounced(key, SETTLE_MS);
  const [lat = 0, lon = 0] = settledKey.split(',').map(Number);
  const moving = settledKey !== key;
  const query = useQuery({
    queryKey: ['geo-locate-map', cityId, lat, lon, locale],
    queryFn: ({ signal }) => geoLocateDistrict({ city_id: cityId, lat, lon }, { signal }),
    enabled: !moving,
    retry: false,
    staleTime: Infinity,
  });
  if (moving || query.isPending) return { kind: 'pending', point };
  if (query.isError) {
    const outside = query.error instanceof ApiError && query.error.status === 404;
    return outside
      ? { kind: 'outside', point }
      : { kind: 'failed', point, retry: () => void query.refetch() };
  }
  // район из того же списка, что и «Где»: выбор — по id, название — на языке экрана
  const district = districts.find((item) => item.id === query.data.id);
  return district
    ? { kind: 'found', district, point }
    : { kind: 'failed', point, retry: () => void query.refetch() };
}
