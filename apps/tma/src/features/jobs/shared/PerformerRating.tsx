// Рейтинг исполнителя там, где клиент выбирает и договаривается (S23–S26): звезда, число и
// «37 отзывов», дальше через «·» район или роль. Рейтинга нет (меньше трёх отзывов) — «Новый
// специалист», как в каталоге (SPEC §5).
import { useFormat, useTranslation } from '@sosed/i18n';
import { Rating } from '@sosed/ui-web';

export function PerformerRating({
  rating,
  count,
  meta,
}: {
  /** Средняя оценка; null — отзывов меньше трёх. */
  rating: number | null;
  count: number;
  meta?: readonly (string | null | undefined)[];
}) {
  const { t } = useTranslation('jobs');
  const { t: common } = useTranslation();
  const format = useFormat();
  return (
    <Rating
      value={rating !== null ? format.rating(rating) : null}
      reviews={t('manage.reviews', { count })}
      newLabel={common('rating.new')}
      meta={meta}
    />
  );
}
