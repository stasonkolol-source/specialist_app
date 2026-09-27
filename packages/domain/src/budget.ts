// Бакеты бюджета на шаге «Бюджет» S20 (PRODUCT, SPEC §4): до 2 000 / 2–5 / 5–10 / 10–30 / 30–100 / 100 тыс.+ RSD.
import type { Para } from './money.ts';
import { rsdToPara } from './money.ts';

export interface BudgetBucket {
  id: 'upTo2k' | '2k-5k' | '5k-10k' | '10k-30k' | '30k-100k' | 'over100k';
  /** para, не включая (у первого бакета — 0 включительно). */
  min: Para;
  /** para, включая; `null` — без верхней границы. */
  max: Para | null;
}

export const BUDGET_BUCKETS: readonly BudgetBucket[] = [
  { id: 'upTo2k', min: 0, max: rsdToPara(2_000) },
  { id: '2k-5k', min: rsdToPara(2_000), max: rsdToPara(5_000) },
  { id: '5k-10k', min: rsdToPara(5_000), max: rsdToPara(10_000) },
  { id: '10k-30k', min: rsdToPara(10_000), max: rsdToPara(30_000) },
  { id: '30k-100k', min: rsdToPara(30_000), max: rsdToPara(100_000) },
  { id: 'over100k', min: rsdToPara(100_000), max: null },
];

/** Бакет суммы: граница относится к нижнему бакету (2 000 RSD — «до 2 000»). */
export function budgetBucketOf(amount: Para): BudgetBucket {
  const bucket = BUDGET_BUCKETS.find((b) => amount <= (b.max ?? Number.POSITIVE_INFINITY));
  if (!bucket || amount < 0) throw new RangeError(`Сумма вне бакетов: ${amount}`);
  return bucket;
}

/** Выбор бакета — это бюджет-диапазон; у последнего бакета нет верхней границы. */
export function budgetFromBucket(bucket: BudgetBucket): {
  type: 'range';
  min: Para;
  max: Para | null;
} {
  return { type: 'range', min: bucket.min, max: bucket.max };
}
