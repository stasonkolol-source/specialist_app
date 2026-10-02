import type { DistrictOut } from '@sosed/api-client';
import { describe, expect, it } from 'vitest';

import { distanceMeters, nearestDistrict } from './districts.ts';

const district = (
  id: number,
  name: string,
  lat: number,
  lon: number,
  kind: DistrictOut['kind'] = 'neighborhood',
): DistrictOut => ({ id, slug: name, name, kind, parent_id: 1, center: { lat, lon } });

const NOVI_SAD = [
  district(1, 'Нови-Сад', 45.2551, 19.8452, 'municipality'),
  district(11, 'Лиман', 45.2449, 19.8435),
  district(12, 'Грбавица', 45.2506, 19.8294),
  district(13, 'Детелинара', 45.2635, 19.8165),
];

describe('nearestDistrict', () => {
  it('picks the neighbourhood whose centre is closest, never the whole city', () => {
    expect(nearestDistrict(NOVI_SAD, { lat: 45.2455, lon: 19.844 })?.name).toBe('Лиман');
    expect(nearestDistrict(NOVI_SAD, { lat: 45.2551, lon: 19.8452 })?.name).not.toBe('Нови-Сад');
    expect(nearestDistrict([], { lat: 45.25, lon: 19.84 })).toBeNull();
  });

  it('measures distance on the sphere', () => {
    // Лиман — Детелинара по прямой ≈ 3 км
    const meters = distanceMeters({ lat: 45.2449, lon: 19.8435 }, { lat: 45.2635, lon: 19.8165 });
    expect(meters).toBeGreaterThan(2_800);
    expect(meters).toBeLessThan(3_200);
  });
});
