// Ближайший район к точке клиента (DEVELOPMENT_PLAN 4.8): чип «Нови-Сад · Лиман» на Главной S03.
// Центры районов — из справочника (GET /cities/{id}/districts); расстояние — по сфере, без
// базы: районов в городе десятки.
import type { DistrictOut } from '@sosed/api-client';

const EARTH_RADIUS_M = 6_371_000;
const NEIGHBORHOOD = 'neighborhood';

const radians = (degrees: number) => (degrees * Math.PI) / 180;

/** Расстояние по большому кругу, метры. */
export function distanceMeters(
  a: { lat: number; lon: number },
  b: { lat: number; lon: number },
): number {
  const dLat = radians(b.lat - a.lat);
  const dLon = radians(b.lon - a.lon);
  const h =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(radians(a.lat)) * Math.cos(radians(b.lat)) * Math.sin(dLon / 2) ** 2;
  return 2 * EARTH_RADIUS_M * Math.asin(Math.sqrt(h));
}

/** Квартал, чей центр ближе всего к точке; муниципалитет «весь город» не считается. */
export function nearestDistrict(
  districts: readonly DistrictOut[],
  point: { lat: number; lon: number },
): DistrictOut | null {
  let best: DistrictOut | null = null;
  let bestDistance = Infinity;
  for (const district of districts) {
    if (district.kind !== NEIGHBORHOOD) continue;
    const distance = distanceMeters(point, district.center);
    if (distance < bestDistance) {
      best = district;
      bestDistance = distance;
    }
  }
  return best;
}
