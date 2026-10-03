// S28 «Сделки и отзывы» (DEVELOPMENT_PLAN 7.3): вкладка «Сделки» — свои сделки в обеих ролях,
// «Активные» и «Завершённые»: вторая сторона, дата, цена, статус и роль («Вы — клиент»); у
// завершённой — «Отзыв оставлен» со звёздами или «Оставить отзыв» (S27), у отменённой — кто
// отменил. Вкладка «Отзывы» — «Обо мне» (опубликованные, ответ — один, виден после проверки) и
// «Мои» (в любом статусе, с ответом исполнителя). Вход — строка «Сделки и отзывы» в S31, ссылка
// `m_reviews` (уведомление о новом отзыве) открывает вкладку «Отзывы».
import type { HistoryDealOut, MyReviewOut, ReviewsDirection } from '@sosed/api-client';
import { ApiError } from '@sosed/api-client';
import { pagedItems, useDealHistory, useMyReviews, useReplyToReview } from '@sosed/hooks';
import { useFormat, useTranslation } from '@sosed/i18n';
import { useBackButton } from '@sosed/platform';
import {
  Avatar,
  Badge,
  Banner,
  Button,
  Card,
  EmptyState,
  Field,
  Heading,
  Price,
  Segmented,
  Sheet,
  Skeleton,
  Stars,
  Text,
  Textarea,
} from '@sosed/ui-web';
import { useRouter, useSearch } from '@tanstack/react-router';
import type { MouseEvent } from 'react';
import { useState } from 'react';

import { LoadError } from '../shared/LoadError.tsx';
import { useOfferPrice } from '../shared/labels.ts';
import type { HistorySearch } from '../shared/paths.ts';
import { ACCOUNT_PATH, dealPath, reviewPath } from '../shared/paths.ts';

type Tab = 'deals' | 'reviews';
const ACTIVE = new Set(['proposed', 'agreed', 'disputed']);
const STATUS_TONE = {
  proposed: 'info',
  agreed: 'ok',
  completed: 'ok',
  cancelled: undefined,
  disputed: 'urgent',
} as const;
const MAX_REPLY = 2000;
/** Статус отзыва и ответа (`under_review`, `published`, `removed`): API отдаёт строкой. */
type ReviewState = 'under_review' | 'published' | 'removed';

export function HistoryScreen() {
  const { t } = useTranslation('jobs');
  const router = useRouter();
  const search = useSearch({ strict: false }) as HistorySearch;
  const [tab, setTab] = useState<Tab>(search.tab === 'reviews' ? 'reviews' : 'deals');
  useBackButton(() => {
    if (router.history.canGoBack()) router.history.back();
    else void router.navigate({ to: ACCOUNT_PATH, replace: true });
  });
  return (
    <section className="flex flex-col gap-3 px-4 pt-3 pb-6">
      <Heading variant="h1">{t('history.title')}</Heading>
      <Segmented<Tab>
        label={t('history.title')}
        value={tab}
        onChange={setTab}
        options={[
          { value: 'deals', label: t('history.tabs.deals') },
          { value: 'reviews', label: t('history.tabs.reviews') },
        ]}
      />
      {tab === 'deals' ? <Deals /> : <Reviews />}
    </section>
  );
}

function Deals() {
  const { t } = useTranslation('jobs');
  const history = useDealHistory();
  const items = pagedItems(history.data);
  if (history.isError && items.length === 0) {
    return (
      <LoadError
        error={history.error}
        onRetry={() => void history.refetch()}
        retrying={history.isRefetching}
      />
    );
  }
  if (!history.data) return <Loading />;
  if (items.length === 0) {
    return (
      <EmptyState icon="briefcase" title={t('history.emptyTitle')}>
        {t('history.emptyText')}
      </EmptyState>
    );
  }
  const active = items.filter((deal) => ACTIVE.has(deal.status));
  const finished = items.filter((deal) => !ACTIVE.has(deal.status));
  return (
    <>
      {active.length > 0 && <DealGroup title={t('history.active')} deals={active} />}
      {finished.length > 0 && <DealGroup title={t('history.finished')} deals={finished} />}
      {history.hasNextPage && (
        <Button
          variant="secondary"
          onClick={() => void history.fetchNextPage()}
          disabled={history.isFetchingNextPage}
          aria-busy={history.isFetchingNextPage}
        >
          {t('history.more')}
        </Button>
      )}
    </>
  );
}

function DealGroup({ title, deals }: { title: string; deals: HistoryDealOut[] }) {
  return (
    <div className="flex flex-col gap-2">
      <h2 className="m-0 text-cap font-semibold tracking-wide text-text2 uppercase">{title}</h2>
      {deals.map((deal) => (
        <DealItem key={deal.id} deal={deal} />
      ))}
    </div>
  );
}

function DealItem({ deal }: { deal: HistoryDealOut }) {
  const { t } = useTranslation('jobs');
  const format = useFormat();
  const router = useRouter();
  const offerPrice = useOfferPrice();
  const name = deal.counterpart.display_name || t('history.deleted');
  const at = deal.scheduled_at ?? deal.completed_at ?? deal.created_at;
  const price =
    deal.price.type === null || deal.price.type === 'negotiable'
      ? t('card.negotiable')
      : offerPrice({ type: deal.price.type, amount: deal.price.amount });
  const open = (event: MouseEvent<HTMLElement>) => {
    event.preventDefault();
    void router.navigate({ to: dealPath(deal.id) });
  };
  return (
    <Card tight as="article" aria-label={deal.title}>
      <a
        href={router.history.createHref(dealPath(deal.id))}
        onClick={open}
        className="flex items-start gap-3 text-text no-underline"
      >
        <Avatar name={name} />
        <span className="flex min-w-0 grow flex-col gap-0.5">
          <span className="text-title">{deal.title}</span>
          <Text as="span" variant="cap">
            {`${name} · ${format.calendar(new Date(at))}`}
          </Text>
        </span>
        <Price>{price}</Price>
      </a>
      <Footer deal={deal} />
    </Card>
  );
}

/** Низ карточки: статус и роль, отзыв по завершённой, кто отменил отменённую. */
function Footer({ deal }: { deal: HistoryDealOut }) {
  const { t } = useTranslation('jobs');
  const router = useRouter();
  if (deal.status === 'completed') {
    if (deal.my_review) {
      return (
        <div className="flex items-center justify-between gap-2">
          <Badge tone="ok">{t('history.reviewLeft')}</Badge>
          <Stars
            value={deal.my_review.rating}
            label={t('review.star', { count: deal.my_review.rating })}
            starLabel={(count) => t('review.star', { count })}
          />
        </div>
      );
    }
    if (deal.review_until) {
      return (
        <div className="flex items-center justify-between gap-2">
          <Text as="span" variant="sm" secondary>
            {t('history.reviewNone')}
          </Text>
          <Button size="sm" onClick={() => void router.navigate({ to: reviewPath(deal.id) })}>
            {t('history.leaveReview')}
          </Button>
        </div>
      );
    }
  }
  if (deal.status === 'cancelled') {
    const by =
      deal.cancelled_by_me === true
        ? 'me'
        : deal.cancelled_by_me === false
          ? deal.counterpart.role
          : 'system';
    return (
      <div className="flex items-center justify-between gap-2">
        <Badge>{t('deal.status.cancelled')}</Badge>
        <Text as="span" variant="sm" secondary>
          {t(`history.cancelledBy.${by}`)}
        </Text>
      </div>
    );
  }
  return (
    <div className="flex items-center justify-between gap-2">
      <Badge tone={STATUS_TONE[deal.status]}>{t(`deal.status.${deal.status}`)}</Badge>
      <Text as="span" variant="sm" secondary>
        {t(`history.you.${deal.my_role}`)}
      </Text>
    </div>
  );
}

function Reviews() {
  const { t } = useTranslation('jobs');
  const [direction, setDirection] = useState<ReviewsDirection>('received');
  const reviews = useMyReviews(direction);
  const [replying, setReplying] = useState<MyReviewOut | null>(null);
  const items = pagedItems(reviews.data);
  return (
    <>
      <Segmented<ReviewsDirection>
        label={t('history.tabs.reviews')}
        value={direction}
        onChange={setDirection}
        options={[
          { value: 'received', label: t('history.received') },
          { value: 'written', label: t('history.written') },
        ]}
      />
      {reviews.isError && items.length === 0 ? (
        <LoadError
          error={reviews.error}
          onRetry={() => void reviews.refetch()}
          retrying={reviews.isRefetching}
        />
      ) : !reviews.data ? (
        <Loading />
      ) : items.length === 0 ? (
        <EmptyState
          icon="star"
          title={t(direction === 'received' ? 'history.emptyReceived' : 'history.emptyWritten')}
        />
      ) : (
        items.map((review) => (
          <ReviewItem
            key={review.id}
            review={review}
            received={direction === 'received'}
            onReply={() => setReplying(review)}
          />
        ))
      )}
      {reviews.hasNextPage && (
        <Button
          variant="secondary"
          onClick={() => void reviews.fetchNextPage()}
          disabled={reviews.isFetchingNextPage}
          aria-busy={reviews.isFetchingNextPage}
        >
          {t('history.more')}
        </Button>
      )}
      {replying && <ReplySheet review={replying} onClose={() => setReplying(null)} />}
    </>
  );
}

function ReviewItem({
  review,
  received,
  onReply,
}: {
  review: MyReviewOut;
  received: boolean;
  onReply: () => void;
}) {
  const { t } = useTranslation('jobs');
  const format = useFormat();
  const name = review.counterpart_name ?? t('history.deleted');
  const reply = review.reply;
  return (
    <Card tight as="article" aria-label={name}>
      <div className="flex items-start justify-between gap-3">
        <span className="flex min-w-0 flex-col gap-0.5">
          <span className="text-title">{name}</span>
          <Text as="span" variant="cap">
            {[review.deal_title, format.date(new Date(review.published_at ?? review.created_at))]
              .filter(Boolean)
              .join(' · ')}
          </Text>
        </span>
        <Stars
          value={review.rating}
          label={t('review.star', { count: review.rating })}
          starLabel={(count) => t('review.star', { count })}
        />
      </div>
      {review.body && (
        <Text as="p" variant="body">
          {review.body}
        </Text>
      )}
      {!received && review.status !== 'published' && (
        <div className="flex">
          <Badge tone={review.status === 'removed' ? 'urgent' : 'info'}>
            {t(`history.reviewStatus.${review.status as ReviewState}`)}
          </Badge>
        </div>
      )}
      {reply && (
        <div className="flex flex-col gap-1 rounded-panel bg-bg2 px-3 py-2">
          <Text as="span" variant="cap">
            {received
              ? `${t('history.yourReply')} · ${t(`history.replyStatus.${reply.status as ReviewState}`)}`
              : t('history.theirReply')}
          </Text>
          <Text as="p" variant="sm">
            {reply.body}
          </Text>
        </div>
      )}
      {received && review.can_reply && (
        <div className="flex">
          <Button size="sm" variant="secondary" onClick={onReply}>
            {t('history.reply')}
          </Button>
        </div>
      )}
    </Card>
  );
}

function ReplySheet({ review, onClose }: { review: MyReviewOut; onClose: () => void }) {
  const { t } = useTranslation('jobs');
  const { t: common } = useTranslation();
  const reply = useReplyToReview();
  const [body, setBody] = useState('');
  const send = () =>
    reply.mutate({ reviewId: review.id, body: { body: body.trim() } }, { onSuccess: onClose });
  return (
    <Sheet
      open
      title={t('history.replyTitle')}
      onClose={onClose}
      closeLabel={common('action.close')}
      footer={
        <Button
          full
          disabled={body.trim() === '' || reply.isPending}
          aria-busy={reply.isPending}
          onClick={send}
        >
          {t('history.replySend')}
        </Button>
      }
    >
      <div className="flex flex-col gap-3">
        {review.body && (
          <Text as="p" variant="sm" secondary>
            {review.body}
          </Text>
        )}
        <Field label={t('history.replyTitle')} hint={t('history.replyHint')}>
          <Textarea
            value={body}
            maxLength={MAX_REPLY}
            onChange={(event) => setBody(event.target.value)}
          />
        </Field>
        {reply.error && (
          <Banner tone="danger" role="alert">
            {reply.error instanceof ApiError && reply.error.status < 500
              ? (reply.error.problem.detail ?? t('history.replyFailed'))
              : t('history.replyFailed')}
          </Banner>
        )}
      </div>
    </Sheet>
  );
}

function Loading() {
  return (
    <div className="flex flex-col gap-2" aria-busy="true">
      <Skeleton className="h-24 w-full" />
      <Skeleton className="h-24 w-full" />
    </div>
  );
}
