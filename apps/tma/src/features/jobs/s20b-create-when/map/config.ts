// Карта выбора точки S20b (Q28, вариант A): своя подложка OpenStreetMap / Protomaps —
// scripts/map/README.md. Здесь — только то, что нужно экрану до загрузки карты: включена ли она и для
// какого города. MapLibre, pmtiles и стиль — ленивым чанком MapPicker: в первый экран не попадают.
import type { DistrictOut } from '@sosed/api-client';

/** База ассетов карты (VITE_MAP_ASSETS_URL): `/map` в dev, CDN R2 на stage и prod. Пусто — карты
 *  нет, район выбирают из списка. */
export function mapAssetsBase(): string | null {
  const base = import.meta.env.VITE_MAP_ASSETS_URL?.trim();
  return base ? base : null;
}

/** Тайлы собраны только для Нови-Сада (scripts/map/build.py): у другого города кнопки карты нет. */
export const MAP_CITY_SLUG = 'novi-sad';

/** Выбор на карте для S20b: точка центра и её район. Точка дальше S20b не уходит — в заявку
 *  попадает только район, как и раньше. */
export interface MapPick {
  lat: number;
  lon: number;
  district: DistrictOut;
}
