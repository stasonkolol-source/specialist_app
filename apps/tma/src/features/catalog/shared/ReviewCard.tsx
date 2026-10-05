// Отзыв по сделке на S08 и S11 (DEVELOPMENT_PLAN 4.6, 7.3): автор «Ирина С.», под именем звёзды с
// месяцем и услуга своей строкой — справа у имени ничего не теснит подпись, «Сентябрь · Люстры и
// карнизы» не переносилась; текст, «Сделка в «Соседях»» и ответ специалиста (прошедший проверку).
// На S11 у имени — «⋯»: жалоба на отзыв (шторка S46, 4.7); на S08 — без неё, как на артборде.
// Отзыв до платформы (вкладка S11, 7.6а): вместо услуги — «что делал мастер», метка «До платформы —
// не подтверждён сделкой» вместо «Сделка в «Соседях»». На S11 метку не показываем: о виде отзывов
// уже говорят вкладка и строка над списком.
import type { CardReviewOut } from '@sosed/api-client';
import { useFormat, useTranslation } from '@sosed/i18n';
import {
  Avatar,
  Badge,
  Card,
  IconButton,
  Skeleton,
  SkeletonCard,
  SkeletonText,
  Stars,
  Text,
} from '@sosed/ui-web';

/** Отзыв, пока не пришёл: автор, звёзды с месяцем, услуга и пара строк текста. */
export function ReviewCardSkeleton() {
  return (
    <SkeletonCard tight>
      <div className="flex items-start gap-2.5">
        <Skeleton round className="size-9 shrink-0" />
        <span className="flex grow flex-col">
          <SkeletonText size="title" className="w-1/3" />
          <SkeletonText size="cap" className="w-1/2" />
          <SkeletonText size="cap" className="w-2/5" />
        </span>
      </div>
      <div className="flex flex-col">
        <SkeletonText size="sm" className="w-full" />
        <SkeletonText size="sm" className="w-2/3" />
      </div>
    </SkeletonCard>
  );
}

export function ReviewCard({
  review,
  onReport,
  showKind = true,
}: {
  review: CardReviewOut;
  /** «⋯» у имени — пожаловаться на отзыв (S11, вошедшему). */
  onReport?: () => void;
  /** Метка вида отзыва: «Сделка в «Соседях»» или «До платформы». На S11 её нет — там вкладки. */
  showKind?: boolean;
}) {
  const { t } = useTranslation('catalog');
  const common = useTranslation().t;
  const format = useFormat();
  const month = format.month(new Date(review.published_at));
  const what = review.category?.name ?? review.work_title ?? null;
  return (
    <Card as="article" tight>
      <div className="flex items-start gap-2.5">
        <Avatar name={review.author_name} size="sm" />
        <span className="flex min-w-0 grow flex-col">
          <span className="flex items-start justify-between gap-2">
            <span className="text-title">{review.author_name}</span>
            {onReport && (
              <IconButton
                plain
                icon="more"
                label={t('reviews.actions', { name: review.author_name })}
                className="-my-2.5 -mr-2"
                onClick={onReport}
              />
            )}
          </span>
          <span className="flex items-center gap-2 text-cap text-text2">
            {/* звёзды 14 px: под именем они подпись, а не заголовок */}
            <span className="[&_svg]:size-3.5">
              <Stars
                value={review.rating}
                label={t('reviews.rating', { rating: review.rating })}
                starLabel={(n) => common('rating.star', { count: n })}
              />
            </span>
            {month}
          </span>
          {what && (
            <Text as="span" variant="cap" className="truncate">
              {what}
            </Text>
          )}
        </span>
      </div>
      {review.body && (
        <Text variant="sm" className="whitespace-pre-line">
          {review.body}
        </Text>
      )}
      {showKind && review.kind === 'deal' && (
        <span className="self-start">
          <Badge tone="ok" icon="check">
            {t('reviews.viaDeal')}
          </Badge>
        </span>
      )}
      {showKind && review.kind === 'pre_platform' && (
        <span className="self-start">
          <Badge tone="mute" icon="clock">
            {t('reviews.prePlatform')}
          </Badge>
        </span>
      )}
      {review.reply && (
        <div className="flex flex-col gap-1 rounded-field bg-bg2 px-3 py-2">
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
