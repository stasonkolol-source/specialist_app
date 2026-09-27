// Счётчик мест, бакеты бюджета, цены, «Новый специалист».
import { describe, expect, it } from 'vitest';

import { BUDGET_BUCKETS, budgetBucketOf, budgetFromBucket } from './budget.ts';
import { paraToRsd, rsdToPara } from './money.ts';
import { budgetAsPrice, validatePrice } from './price.ts';
import { bayesianRating, isNewSpecialist, ratingView } from './rating.ts';
import { respondState, responseSlots } from './slots.ts';

describe('счётчик мест', () => {
  it('«откликов 3 из 5», осталось 2', () => {
    expect(responseSlots({ responsesCount: 3 })).toEqual({
      total: 5,
      taken: 3,
      left: 2,
      isFull: false,
    });
  });

  it('лимит категории и защита от лишних откликов', () => {
    expect(responseSlots({ maxResponses: 3, responsesCount: 7 })).toEqual({
      total: 3,
      taken: 3,
      left: 0,
      isFull: true,
    });
  });

  it('состояние кнопки на S15', () => {
    expect(respondState(responseSlots({ responsesCount: 4 }), false)).toBe('can_respond');
    expect(respondState(responseSlots({ responsesCount: 5 }), false)).toBe('full');
    expect(respondState(responseSlots({ responsesCount: 5 }), true)).toBe('responded');
  });
});

describe('бакеты бюджета', () => {
  it('шесть бакетов подряд без дыр', () => {
    expect(BUDGET_BUCKETS.map((b) => b.id)).toEqual([
      'upTo2k',
      '2k-5k',
      '5k-10k',
      '10k-30k',
      '30k-100k',
      'over100k',
    ]);
    for (let i = 1; i < BUDGET_BUCKETS.length; i += 1) {
      expect(BUDGET_BUCKETS[i]?.min).toBe(BUDGET_BUCKETS[i - 1]?.max);
    }
  });

  it.each([
    [0, 'upTo2k'],
    [2_000, 'upTo2k'],
    [2_000.01, '2k-5k'],
    [5_000, '2k-5k'],
    [7_500, '5k-10k'],
    [30_000, '10k-30k'],
    [100_000, '30k-100k'],
    [250_000, 'over100k'],
  ])('%d RSD → %s', (rsd, id) => {
    expect(budgetBucketOf(rsdToPara(rsd)).id).toBe(id);
  });

  it('выбор бакета — диапазон бюджета', () => {
    const last = BUDGET_BUCKETS.at(-1);
    expect(last && budgetFromBucket(last)).toEqual({ type: 'range', min: 10_000_000, max: null });
    expect(() => budgetBucketOf(-1)).toThrow(RangeError);
  });
});

describe('цены', () => {
  it('para ⇄ RSD', () => {
    expect(rsdToPara(3_500)).toBe(350_000);
    expect(paraToRsd(350_000)).toBe(3_500);
  });

  it('те же правила, что CHECK в БД', () => {
    expect(validatePrice({ type: 'fixed', min: 500_000 })).toEqual([]);
    expect(validatePrice({ type: 'negotiable' })).toEqual([]);
    expect(validatePrice({ type: 'negotiable', min: 1 })).toEqual(['amount_forbidden']);
    expect(validatePrice({ type: 'from' })).toEqual(['amount_required']);
    expect(validatePrice({ type: 'range', min: 400_000 })).toEqual(['max_required']);
    expect(validatePrice({ type: 'range', min: 600_000, max: 400_000 })).toEqual(['max_below_min']);
    expect(validatePrice({ type: 'per_unit', min: 180_000 })).toEqual(['unit_required']);
    expect(validatePrice({ type: 'fixed', min: -1 })).toEqual(['negative']);
  });

  it('бюджет заявки без единицы — «за работу»', () => {
    expect(budgetAsPrice({ type: 'fixed', min: 500_000 })).toEqual({
      type: 'fixed',
      min: 500_000,
      max: null,
      unit: 'work',
    });
  });
});

describe('рейтинг', () => {
  it('«Новый специалист», пока отзывов меньше 3', () => {
    expect([0, 1, 2, 3].map(isNewSpecialist)).toEqual([true, true, true, false]);
    expect(ratingView(2, 5)).toEqual({ kind: 'new', reviewsCount: 2 });
    expect(ratingView(37, 4.9)).toEqual({ kind: 'rated', rating: 4.9, reviewsCount: 37 });
    expect(ratingView(10, null)).toEqual({ kind: 'new', reviewsCount: 10 });
  });

  it('байесовское среднее — примеры из ARCHITECTURE §7.9 при m = 4,6', () => {
    expect(bayesianRating(4.6, 5, 1)).toBeCloseTo(4.67, 2);
    expect(bayesianRating(4.6, 4.8 * 40, 40)).toBeCloseTo(4.78, 2);
  });
});
