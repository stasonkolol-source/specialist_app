// Показ рейтинга (ARCHITECTURE §7.9): байесовское среднее, при < 3 отзывах — «Новый специалист».

export const NEW_SPECIALIST_MAX_REVIEWS = 2;
/** Вес априорного среднего категории в байесовском среднем. */
export const RATING_PRIOR_WEIGHT = 5;

export type RatingView =
  { kind: 'new'; reviewsCount: number } | { kind: 'rated'; rating: number; reviewsCount: number };

export function isNewSpecialist(reviewsCount: number): boolean {
  return reviewsCount <= NEW_SPECIALIST_MAX_REVIEWS;
}

/** Рейтинг считает backend; клиент решает только, показывать ли число. */
export function ratingView(reviewsCount: number, rating: number | null): RatingView {
  if (isNewSpecialist(reviewsCount) || rating === null) return { kind: 'new', reviewsCount };
  return { kind: 'rated', rating, reviewsCount };
}

/** `(C·m + Σr) / (C + n)`; нужен для подсказок и сверки с backend. */
export function bayesianRating(categoryMean: number, sum: number, count: number): number {
  return (RATING_PRIOR_WEIGHT * categoryMean + sum) / (RATING_PRIOR_WEIGHT + count);
}
