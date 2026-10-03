// Отзыв по сделке на S08 и S11 (DEVELOPMENT_PLAN 4.6, 7.3): автор «Ирина С.», месяц и услуга,
// звёзды, текст, «Сделка в «Соседях»» и ответ специалиста (прошедший проверку). «Пожаловаться» —
// 4.7.
import type { CardReviewOut } from '@sosed/api-client';
import { useFormat, useTranslation } from '@sosed/i18n';
import {
  Avatar,
  Badge,
  Card,
  Skeleton,
  SkeletonCard,
  SkeletonText,
  Stars,
  Text,
} from '@sosed/ui-web';

/** Отзыв, пока не пришёл: автор с месяцем, звёзды и пара строк текста. */
export function ReviewCardSkeleton() {
  return (
    <SkeletonCard tight>
      <div className="flex items-center justify-between gap-3">
        <span className="flex grow items-center gap-2.5">
          <Skeleton round className="size-9 shrink-0" />
          <span className="flex grow flex-col">
            <SkeletonText className="w-1/3" />
            <SkeletonText size="cap" className="w-1/2" />
          </span>
        </span>
        <Skeleton className="h-4 w-20" />
      </div>
      <div className="flex flex-col">
        <SkeletonText size="sm" className="w-full" />
        <SkeletonText size="sm" className="w-2/3" />
      </div>
    </SkeletonCard>
  );
}

export function ReviewCard({ review }: { review: CardReviewOut }) {
  const { t } = useTranslation('catalog');
  const common = useTranslation().t;
  const format = useFormat();
  const month = format.month(new Date(review.published_at));
  return (
    <Card as="article" tight>
      <div className="flex items-center justify-between gap-3">
        <span className="flex items-center gap-2.5">
          <Avatar name={review.author_name} size="sm" />
          <span className="flex flex-col">
            <span className="font-semibold">{review.author_name}</span>
            <Text as="span" variant="cap">
              {review.category ? `${month} · ${review.category.name}` : month}
            </Text>
          </span>
        </span>
        <Stars
          value={review.rating}
          label={t('reviews.rating', { rating: review.rating })}
          starLabel={(n) => common('rating.star', { count: n })}
        />
      </div>
      {review.body && (
        <Text variant="sm" className="whitespace-pre-line">
          {review.body}
        </Text>
      )}
      {review.kind === 'deal' && (
        <span className="self-start">
          <Badge tone="ok" icon="check">
            {t('reviews.viaDeal')}
          </Badge>
        </span>
      )}
      {review.reply && (
        <div className="flex flex-col gap-1 rounded-panel bg-bg2 px-3 py-2">
          <Text as="span" variant="cap">
            {t('reviews.reply')}
          </Text>
          <Text variant="sm" className="whitespace-pre-line">
            {review.reply.body}
          </Text>
        </div>
      )}
    </Card>
  );
}
