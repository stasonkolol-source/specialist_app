// Выдача S05 (4.4): страницы подряд, что понял сервер, запрос для «Показать N», числа дерева.
import type { SpecialistCardOut, SpecialistPageOut } from '@sosed/api-client';
import { describe, expect, it } from 'vitest';

import { countQuery, countsByCategory, resultItems, resultSummary } from './search.ts';

function card(name: string): SpecialistCardOut {
  return {
    profile_id: name,
    display_name: name,
    headline: null,
    kind: 'pro',
    avatar: null,
    district: null,
    distance_m: null,
    languages: ['ru'],
    category_ids: [5],
    price_from: null,
    price_from_unit: null,
    negotiable: false,
    rating: null,
    rating_count: 0,
    is_new: true,
    available_until: null,
    badges: [],
  };
}

function page(
  items: SpecialistCardOut[],
  extra: Partial<SpecialistPageOut> = {},
): SpecialistPageOut {
  return { items, next_cursor: null, category_ids: [], did_you_mean: null, hints: [], ...extra };
}

describe('выдача', () => {
  it('карточки всех страниц подряд; понятое сервером — по первой', () => {
    const results = {
      pages: [
        page([card('A'), card('B')], { category_ids: [5], did_you_mean: 'Električar' }),
        page([card('C')]),
      ],
    };

    expect(resultItems(results).map((item) => item.display_name)).toEqual(['A', 'B', 'C']);
    expect(resultSummary(results)).toEqual({
      categoryIds: [5],
      didYouMean: 'Električar',
      hints: [],
    });
    expect(resultItems(undefined)).toEqual([]);
  });

  it('«Показать N» считает без порядка и «срочно»', () => {
    expect(
      countQuery({
        city_id: 1,
        q: 'электрик',
        sort: 'rating',
        urgent: true,
        available_today: true,
      }),
    ).toEqual({ city_id: 1, q: 'электрик', available_today: true });
  });

  it('числа дерева — по id категории', () => {
    const counts = countsByCategory({ items: [{ category_id: 1, count: 7 }] });

    expect(counts.get(1)).toBe(7);
    expect(counts.get(2)).toBeUndefined();
  });
});
