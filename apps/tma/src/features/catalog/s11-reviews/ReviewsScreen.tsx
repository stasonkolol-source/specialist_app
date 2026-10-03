// S11 Отзывы о специалисте (DEVELOPMENT_PLAN 4.6): сводка — средняя оценка, звёзды, сколько
// отзывов, распределение оценок и средние по критериям; ниже — отзывы по сделкам, новые первыми.
// Пока отзывов нет — «Отзывов пока нет»: специалист новый. Ответы специалиста под отзывами и
// «Показать ещё» — 7.3. Вкладка «До платформы» — 7.6, «Пожаловаться на отзыв» — 4.7, «Как мы проверяем
// отзывы» (S51) — со своим шагом. Имя и услуга в шапке — из профиля S08 (обычно уже в кэше).
import type { CardRatingOut, CardReviewOut, SpecialistProfileOut } from '@sosed/api-client';
import { isUnavailable, useSpecialistCard, useSpecialistReviews } from '@sosed/hooks';
import { useFormat, useLocale, useTranslation } from '@sosed/i18n';
import { useBackButton } from '@sosed/platform';
import {
  Button,
  Card,
  EmptyState,
  Heading,
  ProgressBar,
  Skeleton,
  Stars,
  Text,
} from '@sosed/ui-web';
import { useParams, useRouter } from '@tanstack/react-router';

import { LoadError } from '../shared/LoadError.tsx';
import { ReviewCard } from '../shared/ReviewCard.tsx';
import { Unavailable } from '../shared/Unavailable.tsx';
import { CARD_PATHS } from '../shared/paths.ts';

/** Критерии оценки отзыва (ARCHITECTURE §7.3 `reviews.criteria`) в порядке артборда. */
const CRITERIA = ['quality', 'punctuality', 'communication', 'price'] as const;
const STARS = [5, 4, 3, 2, 1] as const;

export function ReviewsScreen() {
  const { profileId } = useParams({ strict: false }) as { profileId: string };
  const router = useRouter();
  const locale = useLocale();
  const card = useSpecialistCard(profileId, locale);
  const reviews = useSpecialistReviews(profileId, locale);
  useBackButton(() => {
    if (router.history.canGoBack()) router.history.back();
    else void router.navigate({ to: CARD_PATHS.profile, params: { profileId }, replace: true });
  });

  const first = reviews.data?.pages[0];
  if (card.data && first) {
    return (
      <Reviews
        card={card.data}
        summary={first.summary}
        items={reviews.data?.pages.flatMap((page) => page.items) ?? []}
        more={
          reviews.hasNextPage
            ? {
                load: () => void reviews.fetchNextPage(),
                busy: reviews.isFetchingNextPage,
              }
            : null
        }
      />
    );
  }
  const failed = [card, reviews].find((load) => load.isError);
  if (failed) {
    return isUnavailable(failed.error) ? (
      <Unavailable />
    ) : (
      <section className="flex flex-col px-4 pt-3 pb-6">
        <LoadError
          error={failed.error}
          onRetry={() => {
            for (const load of [card, reviews]) if (load.isError) void load.refetch();
          }}
          retrying={card.isRefetching || reviews.isRefetching}
        />
      </section>
    );
  }
  return (
    <section className="flex flex-col gap-3 px-4 pt-3 pb-6" aria-busy="true">
      <Skeleton className="h-12 w-full" />
      <Skeleton className="h-44 w-full" />
    </section>
  );
}

function Reviews({
  card,
  summary,
  items,
  more,
}: {
  card: SpecialistProfileOut;
  summary: CardRatingOut;
  items: CardReviewOut[];
  more: { load: () => void; busy: boolean } | null;
}) {
  const { t } = useTranslation('catalog');
  const category = card.categories[0]?.name;
  return (
    <section className="flex flex-col gap-3 px-4 pt-3 pb-6">
      <div className="flex flex-col">
        <Heading variant="h2" as="h1">
          {t('reviews.title')}
        </Heading>
        <Text variant="cap">
          {category ? `${card.display_name} · ${category}` : card.display_name}
        </Text>
      </div>
      {summary.count === 0 ? (
        <EmptyState as="h2" icon="star" title={t('reviews.emptyTitle')}>
          {t('reviews.emptyText')}
        </EmptyState>
      ) : (
        <>
          <Summary summary={summary} />
          <Text variant="cap">{t('reviews.policy')}</Text>
          {items.map((review) => (
            <ReviewCard key={review.id} review={review} />
          ))}
          {more && (
            <Button
              variant="secondary"
              onClick={more.load}
              disabled={more.busy}
              aria-busy={more.busy}
            >
              {t('reviews.more')}
            </Button>
          )}
        </>
      )}
    </section>
  );
}

function Summary({ summary }: { summary: CardRatingOut }) {
  const { t } = useTranslation('catalog');
  const common = useTranslation().t;
  const format = useFormat();
  const criteria = CRITERIA.filter((name) => summary.criteria[name] !== undefined);
  const most = Math.max(1, ...summary.distribution);
  const rating = summary.rating ?? 0;
  return (
    <Card as="section">
      <Heading variant="h3" as="h2" className="sr-only">
        {t('reviews.summary')}
      </Heading>
      <div className="flex items-center gap-5">
        <div className="flex shrink-0 flex-col gap-1">
          {summary.rating === null ? (
            <span className="text-title">{common('rating.new')}</span>
          ) : (
            <>
              <span className="font-display text-h1-xl">{format.rating(summary.rating)}</span>
              <Stars
                value={Math.round(rating)}
                label={t('reviews.average', { rating: format.rating(rating) })}
                starLabel={(n) => common('rating.star', { count: n })}
              />
            </>
          )}
          <Text variant="cap">{t('profile.reviews', { count: summary.count })}</Text>
        </div>
        <ul
          aria-label={t('reviews.distribution')}
          className="m-0 flex grow list-none flex-col gap-1 p-0"
        >
          {STARS.map((stars) => {
            const count = summary.distribution[stars - 1] ?? 0;
            return (
              <li key={stars} className="flex items-center gap-2">
                <span aria-hidden="true" className="w-2.5 text-cap text-text2 tabular-nums">
                  {stars}
                </span>
                <span className="grow">
                  <ProgressBar
                    value={count}
                    max={most}
                    label={t('reviews.bar', { stars, count })}
                  />
                </span>
                <span
                  aria-hidden="true"
                  className="w-6 text-right text-cap text-text2 tabular-nums"
                >
                  {count}
                </span>
              </li>
            );
          })}
        </ul>
      </div>
      {criteria.length > 0 && (
        <>
          <div className="h-px bg-line" aria-hidden="true" />
          <dl className="m-0 grid grid-cols-4 gap-2">
            {criteria.map((name) => (
              <div key={name} className="flex flex-col-reverse">
                <dt className="text-cap text-text2">{t(`reviews.criteria.${name}`)}</dt>
                <dd className="m-0 font-semibold">{format.rating(summary.criteria[name] ?? 0)}</dd>
              </div>
            ))}
          </dl>
        </>
      )}
    </Card>
  );
}
