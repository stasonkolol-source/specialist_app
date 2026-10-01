import type { ServiceOut } from '@sosed/api-client';
import { describe, expect, it } from 'vitest';

import { groupServices, moveService, servicePrice } from './prices.ts';

const service = (
  id: string,
  position: number,
  categoryId: number | null,
  extra: Partial<ServiceOut> = {},
): ServiceOut => ({
  id,
  title: id,
  description: null,
  category_id: categoryId,
  price_type: 'fixed',
  price_min: { amount: 200_000, currency: 'RSD' },
  price_max: null,
  unit: null,
  duration_min: null,
  position,
  is_active: true,
  ...extra,
});

const LIST = [
  service('chandelier', 2, 104),
  service('visit', 0, 101),
  service('other', 3, null),
  service('socket', 1, 101),
  service('cornice', 4, 104),
];

describe('groupServices', () => {
  it('follows the profile categories, then the rest, and puts items without a group last', () => {
    const groups = groupServices(LIST, [104, 101]);

    expect(groups.map((g) => [g.categoryId, g.items.map((s) => s.id)])).toEqual([
      [104, ['chandelier', 'cornice']],
      [101, ['visit', 'socket']],
      [null, ['other']],
    ]);
  });
});

describe('moveService', () => {
  it('swaps with the neighbour of the same group across the shared order', () => {
    expect(moveService(LIST, 'cornice', -1)).toEqual([
      'visit',
      'socket',
      'cornice',
      'other',
      'chandelier',
    ]);
    expect(moveService(LIST, 'visit', 1)).toEqual([
      'socket',
      'visit',
      'chandelier',
      'other',
      'cornice',
    ]);
  });

  it('has nowhere to move the first item up or the last item down', () => {
    expect(moveService(LIST, 'visit', -1)).toBeNull();
    expect(moveService(LIST, 'other', 1)).toBeNull();
    expect(moveService(LIST, 'missing', 1)).toBeNull();
  });
});

describe('servicePrice', () => {
  it('passes amounts in para and keeps known units', () => {
    const hourly = service('hour', 0, null, { price_type: 'hourly', unit: 'hour' });
    expect(servicePrice(hourly)).toEqual({ type: 'hourly', min: 200_000, max: null, unit: 'hour' });
    const odd = service('odd', 0, null, { price_type: 'per_unit', unit: 'точка' });
    expect(servicePrice(odd).unit).toBeNull();
  });
});
