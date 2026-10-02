// Типы цены и единицы (ARCHITECTURE §7.3, §7.7): прайс, отклик, бюджет заявки.
import type { Para } from './money.ts';

/** Позиция прайса (`pricing.services.price_type`). */
export const SERVICE_PRICE_TYPES = [
  'fixed',
  'from',
  'range',
  'hourly',
  'per_unit',
  'negotiable',
] as const;
/** Цена в отклике и шаблоне отклика. */
export const RESPONSE_PRICE_TYPES = ['fixed', 'from', 'hourly', 'negotiable'] as const;
/** Бюджет заявки (`jobs.jobs.budget_type`). */
export const BUDGET_TYPES = ['fixed', 'range', 'negotiable'] as const;

export type PriceType = (typeof SERVICE_PRICE_TYPES)[number];
export type ResponsePriceType = (typeof RESPONSE_PRICE_TYPES)[number];
export type BudgetType = (typeof BUDGET_TYPES)[number];

/** Единица бюджета заявки (`jobs.jobs.budget_unit`). */
export const BUDGET_UNITS = ['work', 'hour', 'm2', 'visit', 'item', 'lesson'] as const;
/** Единица позиции прайса (`pricing.services.unit`). */
export const SERVICE_UNITS = ['hour', 'visit', 'item', 'm2', 'lesson', 'km'] as const;

export type BudgetUnit = (typeof BUDGET_UNITS)[number];
export type PriceUnit = BudgetUnit | (typeof SERVICE_UNITS)[number];

export interface Price {
  type: PriceType;
  /** para; нет только у `negotiable`. */
  min?: Para | null;
  /** para; верхняя граница `range`. */
  max?: Para | null;
  unit?: PriceUnit | null;
}

export type PriceError =
  | 'amount_required'
  | 'amount_forbidden'
  | 'max_required'
  | 'max_below_min'
  | 'unit_required'
  | 'negative';

/** Те же правила, что CHECK в БД: сумма есть у всех, кроме договорной; max ≥ min. */
export function validatePrice(price: Price): PriceError[] {
  const errors: PriceError[] = [];
  const { type, min, max } = price;
  if ((min ?? 0) < 0 || (max ?? 0) < 0) errors.push('negative');
  if (type === 'negotiable') {
    if (min != null || max != null) errors.push('amount_forbidden');
    return errors;
  }
  if (min == null) errors.push('amount_required');
  if (type === 'range' && max == null) errors.push('max_required');
  if (min != null && max != null && max < min) errors.push('max_below_min');
  if (type === 'per_unit' && !price.unit) errors.push('unit_required');
  return errors;
}

/** Бюджет заявки как цена: для показа им нужен один форматтер. */
export function budgetAsPrice(budget: {
  type: BudgetType;
  min?: Para | null;
  max?: Para | null;
  unit?: BudgetUnit | null;
}): Price {
  return {
    type: budget.type,
    min: budget.min ?? null,
    max: budget.max ?? null,
    unit: budget.unit ?? 'work',
  };
}

/** Ставка за час ниже этой — подсказка на S20c «меньше минимальной оплаты часа»: минимальная
 *  цена часа в Сербии, округлённо вверх **[Допущение]**, уточнить по закону на год запуска. */
export const MIN_HOURLY_RSD = 400;
