// S27 «Как всё прошло?» (DEVELOPMENT_PLAN 7.3): отзыв клиента по завершённой сделке — вторая
// сторона и сделка, звёзды с подписью («Хорошо»), «Что понравилось?» (качество, пунктуальность,
// общение, соответствие цене — отмеченным ставится оценка отзыва), текст до 2000 знаков, «Фото к
// отзыву — скоро» (v1); отзыв появится после автоматической проверки и не редактируется.
// MainButton «Опубликовать отзыв» — после выбора оценки. Вход: S26 и S28 «Оставить отзыв», бот —
// через сделку. Сделка не завершена, срок прошёл или отзыв уже есть — объяснение и «К сделке».
import type { DealCardOut, ReviewIn } from '@sosed/api-client';
import { ApiError } from '@sosed/api-client';
import { isUnavailable, useDealCard, useLeaveReview } from '@sosed/hooks';
import { useFormat, useTranslation } from '@sosed/i18n';
import { useBackButton } from '@sosed/platform';
import {
  Avatar,
  Banner,
  Button,
  Card,
  Chip,
  Chips,
  EmptyState,
  Field,
  Heading,
  ChipSkeleton,
  FieldSkeleton,
  Skeleton,
  SkeletonCard,
  SkeletonText,
  Stars,
  Text,
  Textarea,
} from '@sosed/ui-web';
import { useParams, useRouter } from '@tanstack/react-router';
import { useState } from 'react';

import { LoadError } from '../shared/LoadError.tsx';
import { useStepButton } from '../shared/flow.ts';
import { dealPath, jobIdOf } from '../shared/paths.ts';

const CRITERIA = ['quality', 'punctuality', 'communication', 'price'] as const;
type Grade = 1 | 2 | 3 | 4 | 5;
type Criterion = (typeof CRITERIA)[number];
const MAX_BODY = 2000;

export function ReviewScreen() {
  const { dealId: raw = '' } = useParams({ strict: false });
  const dealId = jobIdOf(raw);
  const router = useRouter();
  const card = useDealCard(dealId);
  // отправленный отзыв: карточка сделки перечитается с ним — экран остаётся на «Спасибо»
  const [sent, setSent] = useState(false);
  const back = () => {
    if (router.history.canGoBack()) router.history.back();
    else void router.navigate({ to: dealPath(raw), replace: true });
  };
  useBackButton(back);

  if (sent)
    return <Sent onDeal={() => void router.navigate({ to: dealPath(raw), replace: true })} />;
  if (dealId === null || (card.isError && isUnavailable(card.error))) {
    return <Closed text={null} onDeal={() => void router.navigate({ to: dealPath(raw) })} />;
  }
  if (card.isError) {
    return (
      <section className="px-4 pt-6">
        <LoadError
          error={card.error}
          onRetry={() => void card.refetch()}
          retrying={card.isRefetching}
        />
      </section>
    );
  }
  if (!card.data) return <Loading />;
  const deal = card.data;
  const toDeal = () => void router.navigate({ to: dealPath(deal.id), replace: true });
  if (deal.review_until === null) return <Closed text={reason(deal)} onDeal={toDeal} />;
  return <Form deal={deal} onSent={() => setSent(true)} />;
}

/** Почему отзыв здесь не оставить. */
function reason(deal: DealCardOut): 'exists' | 'notClient' | 'notCompleted' | 'closed' {
  if (deal.my_review !== null) return 'exists';
  if (deal.my_role !== 'client') return 'notClient';
  if (deal.status !== 'completed') return 'notCompleted';
  return 'closed';
}

function Form({ deal, onSent }: { deal: DealCardOut; onSent: () => void }) {
  const { t } = useTranslation('jobs');
  const format = useFormat();
  const leave = useLeaveReview(deal.id);
  const [rating, setRating] = useState(0);
  const [liked, setLiked] = useState<ReadonlySet<Criterion>>(new Set());
  const [body, setBody] = useState('');
  const name = deal.counterpart.display_name || t('deal.deletedParty');
  const done = deal.timeline.completed_at;
  const toggle = (criterion: Criterion) =>
    setLiked((current) => {
      const next = new Set(current);
      if (next.has(criterion)) next.delete(criterion);
      else next.add(criterion);
      return next;
    });
  const submit = () => {
    const review: ReviewIn = {
      rating,
      criteria: Object.fromEntries([...liked].map((criterion) => [criterion, rating])),
      body: body.trim() || null,
    };
    leave.mutate(review, { onSuccess: onSent });
  };
  useStepButton({
    text: t('review.submit'),
    visible: true,
    enabled: rating > 0,
    loading: leave.isPending,
    onClick: submit,
  });

  return (
    <section className="flex flex-col gap-4 px-4 pt-3 pb-6">
      {/* заголовок внутреннего экрана — .h2, как на артборде, а не крупный .h1 раздела */}
      <Heading variant="h2" as="h1">
        {t('review.title')}
      </Heading>
      <Card tight>
        <div className="flex items-center gap-3">
          <Avatar name={name} />
          <div className="flex min-w-0 flex-col gap-0.5">
            <span className="text-title">{name}</span>
            <Text as="span" variant="cap">
              {done
                ? t('review.dealLine', { title: deal.title, date: format.calendar(new Date(done)) })
                : deal.title}
            </Text>
          </div>
        </div>
      </Card>
      <div className="flex flex-col items-center gap-1">
        <Stars
          value={rating}
          onChange={setRating}
          label={t('review.rating')}
          starLabel={(count) => t('review.star', { count })}
        />
        <Text as="p" variant="title" aria-live="polite">
          {rating > 0 ? t(`review.grade.${rating as Grade}`) : ' '}
        </Text>
      </div>
      <div className="flex flex-col gap-2">
        <Heading variant="h3" as="h2">
          {t('review.liked')}
        </Heading>
        <Chips wrap>
          {CRITERIA.map((criterion) => (
            <Chip key={criterion} selected={liked.has(criterion)} onClick={() => toggle(criterion)}>
              {t(`review.criteria.${criterion}`)}
            </Chip>
          ))}
        </Chips>
      </div>
      <Field label={t('review.body')} hint={t('review.hint')}>
        <Textarea
          value={body}
          maxLength={MAX_BODY}
          placeholder={t('review.placeholder')}
          onChange={(event) => setBody(event.target.value)}
        />
      </Field>
      {/* фото к отзыву — v1: строкой, без плитки — пунктир читался как загрузка, но не нажимался */}
      <Text as="p" variant="cap">
        {t('review.photoSoon')}
      </Text>
      <Text as="p" variant="cap">
        {t('review.note')}
      </Text>
      {leave.error && (
        <Banner tone="danger" role="alert">
          {leave.error instanceof ApiError && leave.error.status < 500
            ? (leave.error.problem.detail ?? t('review.failed'))
            : t('review.failed')}
        </Banner>
      )}
    </section>
  );
}

function Sent({ onDeal }: { onDeal: () => void }) {
  const { t } = useTranslation('jobs');
  return (
    <section className="flex flex-col gap-4 px-4 pt-10 pb-6">
      <EmptyState
        as="h1"
        size="h2"
        tone="accent"
        icon="check"
        title={t('review.sent')}
        action={<Button onClick={onDeal}>{t('review.toDeal')}</Button>}
      />
    </section>
  );
}

function Closed({ text, onDeal }: { text: ReturnType<typeof reason> | null; onDeal: () => void }) {
  const { t } = useTranslation('jobs');
  return (
    <section className="flex flex-col px-4 pt-10 pb-6">
      <EmptyState
        as="h1"
        size="h2"
        tone="neutral"
        icon="star"
        title={text ? t(`review.${text}`) : t('deal.unavailable')}
        action={
          <Button variant="secondary" onClick={onDeal}>
            {t('review.toDeal')}
          </Button>
        }
      />
    </section>
  );
}

function Loading() {
  return (
    <section className="flex flex-col gap-4 px-4 pt-3 pb-6" aria-busy="true">
      <SkeletonText size="h1" screen className="w-2/3" />
      {/* кому отзыв */}
      <SkeletonCard tight>
        <div className="flex items-center gap-3">
          <Skeleton round className="size-12 shrink-0" />
          <div className="flex min-w-0 grow flex-col gap-0.5">
            <SkeletonText size="title" className="w-2/5" />
            <SkeletonText size="cap" className="w-3/5" />
          </div>
        </div>
      </SkeletonCard>
      {/* звёзды, критерии и текст */}
      <Skeleton screen className="h-9 w-48 self-center" />
      <div className="flex flex-wrap gap-2">
        {['w-28', 'w-24', 'w-32', 'w-20'].map((width) => (
          <ChipSkeleton key={width} className={width} />
        ))}
      </div>
      <FieldSkeleton tall />
    </section>
  );
}
