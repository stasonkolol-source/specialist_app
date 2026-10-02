import type { CardPhotoOut, CardServiceOut } from '@sosed/api-client';
import { ApiError } from '@sosed/api-client';
import { describe, expect, it } from 'vitest';

import { servicePrice } from '../specialist/prices.ts';
import { isUnavailable, largestVariant, priceGroups } from './card.ts';

const service = (id: string, categoryId: number | null): CardServiceOut => ({
  id,
  title: id,
  description: null,
  category_id: categoryId,
  price_type: 'fixed',
  price_min: { amount: 200_000, currency: 'RSD' },
  price_max: null,
  unit: 'visit',
  duration_min: 60,
});

const problem = (status: number) =>
  new ApiError({ type: 'x', title: 'x', status, code: 'x', trace_id: null });

describe('priceGroups', () => {
  it('keeps the server order of groups and puts items without a known group last', () => {
    const groups = priceGroups({
      items: [
        service('visit', 101),
        service('other', null),
        service('lamp', 104),
        service('gone', 7),
      ],
      categories: [
        { id: 101, name: 'Выезд' },
        { id: 104, name: 'Люстры и свет' },
      ],
    });

    expect(
      groups.map((group) => [group.category?.id ?? null, group.items.map((s) => s.id)]),
    ).toEqual([
      [101, ['visit']],
      [104, ['lamp']],
      [null, ['other', 'gone']],
    ]);
  });
});

describe('isUnavailable', () => {
  it('treats a hidden or unknown profile and a broken link as unavailable, not as an error', () => {
    expect(isUnavailable(problem(404))).toBe(true);
    expect(isUnavailable(problem(422))).toBe(true);
    expect(isUnavailable(problem(500))).toBe(false);
    expect(isUnavailable(new Error('offline'))).toBe(false);
  });
});

describe('largestVariant', () => {
  it('picks the widest variant for the viewer', () => {
    const photo: CardPhotoOut = {
      placeholder: null,
      variants: [
        { name: 'md', url: 'md.webp', width: 800, height: 600 },
        { name: 'lg', url: 'lg.webp', width: 1600, height: 1200 },
        { name: 'thumb', url: 'thumb.webp', width: 320, height: 240 },
      ],
    };

    expect(largestVariant(photo)?.name).toBe('lg');
  });
});

describe('servicePrice for a card', () => {
  it('reads the price type from a string and falls back to negotiable for an unknown one', () => {
    expect(servicePrice(service('visit', 101))).toEqual({
      type: 'fixed',
      min: 200_000,
      max: null,
      unit: 'visit',
    });
    expect(servicePrice({ ...service('x', null), price_type: 'auction' }).type).toBe('negotiable');
  });
});
