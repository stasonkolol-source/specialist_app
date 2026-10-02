// S23 Своя заявка (DEVELOPMENT_PLAN 5.6): статус («Приём откликов», «На проверке», «Нужно
// исправить» с причиной модерации) и когда опубликована, «когда», район («точный адрес откроется
// выбранному»), бюджет, места «3 из 5 откликов · осталось 2 места», просмотры. «Пригласить» —
// шторка с подходящими специалистами из каталога (категория и город заявки), «Продлить» — когда
// срок на исходе или вышел, «Поднять» — v1. Отклики — карточками по времени отклика: фото и имя,
// рейтинг или «Отзывов пока нет», район, цена, сообщение, «Откликнулся первым», «Телефон
// подтверждён», «Подработка», «Новый»; опрос раз в 15 секунд. «Закрыть заявку» спрашивает
// причину. «Изменить» — мастер S20a–d с этой заявкой (`?edit=<id>`, сохранение с If-Match).
// Выбор исполнителя (S24) — 6.2, «Поделиться» — 7.4.
import type { JobCloseInReason, JobOut, ResponseCardOut } from '@sosed/api-client';
import { ApiError } from '@sosed/api-client';
import { isUnavailable, useCloseJob, useExtendJob, useJob, useResponseCards } from '@sosed/hooks';
import { useFormat, useTranslation } from '@sosed/i18n';
import { useBackButton, useBottomButtonState } from '@sosed/platform';
import {
  Avatar,
  Badge,
  Banner,
  Button,
  Card,
  EmptyState,
  Group,
  Heading,
  Icon,
  Price,
  Row,
  Sheet,
  Skeleton,
  Text,
} from '@sosed/ui-web';
import { Navigate, useParams, useRouter } from '@tanstack/react-router';
import { useId, useState } from 'react';

import { InviteList } from '../shared/InviteList.tsx';
import { JobUnavailable } from '../shared/JobUnavailable.tsx';
import { useDraftStore } from '../shared/draft.ts';
import { LoadError } from '../shared/LoadError.tsx';
import { useBudgetText, useDistrictName, useOfferPrice, useWhenBadge } from '../shared/labels.ts';
import { CREATE_PATHS, JOBS_PATHS, jobIdOf, jobPath } from '../shared/paths.ts';

const REASONS: readonly JobCloseInReason[] = [
  'hired_here',
  'hired_elsewhere',
  'not_needed',
  'no_suitable',
];
const MAX_EXTENSIONS = 3;
const DAY_MS = 24 * 60 * 60 * 1000;
/** Что можно править: опубликованную, ждущую проверки и возвращённую модерацией. */
const EDITABLE: ReadonlySet<JobOut['status']> = new Set([
  'published',
  'pending_moderation',
  'rejected',
]);

export function ManageJobScreen() {
  const { jobId: raw = '' } = useParams({ strict: false });
  const jobId = jobIdOf(raw);
  const job = useJob(jobId);
  const router = useRouter();
  useBackButton(() => {
    if (router.history.canGoBack()) router.history.back();
    else void router.navigate({ to: JOBS_PATHS.mine, replace: true });
  });

  if (jobId === null || (job.isError && isUnavailable(job.error))) {
    return <JobUnavailable onFeed={() => void router.navigate({ to: JOBS_PATHS.mine })} />;
  }
  if (job.isError) {
    return (
      <section className="px-4 pt-6">
        <LoadError
          error={job.error}
          onRetry={() => void job.refetch()}
          retrying={job.isRefetching}
        />
      </section>
    );
  }
  if (!job.data) return <Loading />;
  // чужая заявка — экран исполнителя S15
  if (job.data.viewer_role !== 'owner') return <Navigate to={jobPath(job.data.id)} replace />;
  return <Manage job={job.data} />;
}

function Manage({ job }: { job: JobOut }) {
  const { t } = useTranslation('jobs');
  const router = useRouter();
  const cards = useResponseCards(job.id);
  const close = useCloseJob();
  const extend = useExtendJob();
  const [closing, setClosing] = useState(false);
  const [inviting, setInviting] = useState(false);
  const published = job.status === 'published';
  const items = cards.data?.items ?? [];
  const failed = close.error ?? extend.error;
  const responsesId = useId();

  return (
    <section className="flex flex-col gap-3.5 px-4 pt-3 pb-6">
      <Summary
        job={job}
        onEdit={() => {
          // правка — всегда с версии, которую видно сейчас
          useDraftStore.getState().edit(job);
          void router.navigate({ to: CREATE_PATHS.what, search: { edit: job.id } });
        }}
        onInvite={() => setInviting(true)}
        onExtend={() => extend.mutate(job.id)}
        extending={extend.isPending}
      />
      {failed && <ActionError error={failed} />}
      {job.status === 'rejected' && (
        <Banner tone="danger" role="status">
          {t('manage.rejected', { reason: job.moderation_note ?? '' })}
        </Banner>
      )}
      {job.status === 'pending_moderation' && (
        <Banner tone="info" icon="clock">
          {t('manage.review')}
        </Banner>
      )}
      {published && items.length > 0 && (
        <Banner tone="info" icon="lock">
          {t('manage.chooseHint')}
        </Banner>
      )}
      <section className="flex flex-col gap-2.5" aria-labelledby={responsesId}>
        <div className="flex items-center justify-between gap-3 px-1">
          <Heading variant="h3" as="h2" id={responsesId}>
            {t('manage.responses')}
          </Heading>
          {items.length > 1 && (
            <Text as="span" variant="cap">
              {t('manage.byTime')}
            </Text>
          )}
        </div>
        {cards.isError && !cards.data ? (
          <LoadError
            error={cards.error}
            onRetry={() => void cards.refetch()}
            retrying={cards.isRefetching}
          />
        ) : !cards.data ? (
          <Skeleton radius="card" className="h-32 w-full" />
        ) : items.length === 0 ? (
          <EmptyState as="h3" icon="send" title={t('manage.noResponsesTitle')}>
            {published ? t('manage.noResponsesText') : null}
          </EmptyState>
        ) : (
          items.map((card) => <ResponseCard key={card.id} card={card} />)
        )}
      </section>
      {(published ||
        job.status === 'pending_moderation' ||
        job.status === 'rejected' ||
        job.status === 'expired') && (
        <Group>
          <Row
            title={<span className="text-danger">{t('manage.close')}</span>}
            subtitle={t('manage.closeHint')}
            icon="x"
            onClick={() => setClosing(true)}
          />
        </Group>
      )}
      {closing && (
        <CloseSheet
          onClose={() => setClosing(false)}
          onPick={(reason) =>
            close.mutate({ jobId: job.id, reason }, { onSettled: () => setClosing(false) })
          }
          busy={close.isPending}
        />
      )}
      {inviting && <InviteSheet job={job} onClose={() => setInviting(false)} />}
    </section>
  );
}

/** Карточка заявки: статус, «когда», район, бюджет, места, просмотры и действия. */
function Summary({
  job,
  onEdit,
  onInvite,
  onExtend,
  extending,
}: {
  job: JobOut;
  onEdit: () => void;
  onInvite: () => void;
  onExtend: () => void;
  extending: boolean;
}) {
  const { t } = useTranslation('jobs');
  const { t: common } = useTranslation();
  const format = useFormat();
  const whenBadge = useWhenBadge();
  const budgetText = useBudgetText();
  const place = useDistrictName(job.city_id, job.district_id);
  const titleId = useId();
  const published = job.status === 'published';
  const budget = budgetText(job, { unit: false });
  const unit = common(`unit.${job.budget_unit}`);
  const kind = job.budget_type === 'negotiable' ? null : t(`manage.budgetTypes.${job.budget_type}`);
  const left = Math.max(job.max_responses - job.responses_count, 0);
  const expires = job.expires_at ? new Date(job.expires_at).getTime() : null;
  // «скоро истечёт» — от момента открытия экрана
  const [now] = useState(() => Date.now());
  const canExtend =
    job.extensions_count < MAX_EXTENSIONS &&
    (job.status === 'expired' || (published && expires !== null && expires - now < DAY_MS));
  return (
    <Card as="section" aria-labelledby={titleId}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Badge
          tone={published ? 'ok' : job.status === 'rejected' ? 'danger' : 'mute'}
          dot={published}
        >
          {t(`mine.status.${job.status}`)}
        </Badge>
        {job.published_at && (
          <Text as="span" variant="cap">
            {t('manage.publishedAgo', { time: format.relative(new Date(job.published_at)) })}
          </Text>
        )}
      </div>
      <Heading variant="h2" as="h1" id={titleId}>
        {job.title}
      </Heading>
      <div className="flex flex-col gap-2 text-cap text-text2">
        <p className="m-0 flex items-center gap-1.5">
          <Icon name="clock" size={16} className="shrink-0" />
          {whenBadge(job, true).label}
        </p>
        {place && (
          <p className="m-0 flex items-center gap-1.5">
            <Icon name="pin" size={16} className="shrink-0" />
            {t('manage.place', { place })}
          </p>
        )}
        <p className="m-0 flex items-center gap-1.5">
          <Icon name="wallet" size={16} className="shrink-0" />
          {budget
            ? [budget, [kind, unit].filter(Boolean).join(', ')].join(' · ')
            : t('card.negotiable')}
        </p>
        {job.views_count !== null && (
          <p className="m-0 flex items-center gap-1.5">
            <Icon name="eye" size={16} className="shrink-0" />
            {t('manage.views', { count: job.views_count })}
          </p>
        )}
      </div>
      <div className="flex items-center gap-2.5">
        <span aria-hidden="true" className="flex gap-0.75">
          {Array.from({ length: job.max_responses }, (_, index) => (
            <i
              key={index}
              className={
                index < job.responses_count
                  ? 'h-1.5 w-3.5 rounded-full bg-accent'
                  : 'h-1.5 w-3.5 rounded-full bg-line'
              }
            />
          ))}
        </span>
        <span className="text-sm">
          <b>{t('manage.slotsTaken', { count: job.responses_count, total: job.max_responses })}</b>{' '}
          {t('manage.slotsRest', {
            left: left > 0 ? common('count.slotsLeft', { count: left }) : common('count.full'),
          })}
        </span>
      </div>
      <div className="grid grid-cols-2 gap-2">
        {EDITABLE.has(job.status) && (
          <Button variant="outline" icon="edit" onClick={onEdit}>
            {t('manage.edit')}
          </Button>
        )}
        {published && (
          <Button variant="outline" icon="users" onClick={onInvite}>
            {t('manage.invite')}
          </Button>
        )}
        {canExtend && (
          <Button
            variant="outline"
            icon="refresh"
            disabled={extending}
            aria-busy={extending}
            onClick={onExtend}
          >
            {t('manage.extend')}
          </Button>
        )}
        {published && (
          <Button variant="outline" icon="zap" disabled>
            {t('manage.raise')}
            <Badge>{t('manage.soon')}</Badge>
          </Button>
        )}
      </div>
    </Card>
  );
}

/** Отклик: исполнитель, цена, сообщение и бейджи. Выбор исполнителя (S24) — 6.2. */
function ResponseCard({ card }: { card: ResponseCardOut }) {
  const { t } = useTranslation('jobs');
  const format = useFormat();
  const offerPrice = useOfferPrice();
  const { performer } = card;
  const name = performer.display_name || '—';
  const avatar =
    performer.avatar?.variants.find((v) => v.name === 'thumb') ?? performer.avatar?.variants[0];
  const price = card.price.type === 'negotiable' ? t('card.negotiable') : offerPrice(card.price);
  const meta = [
    performer.rating !== null
      ? `${format.rating(performer.rating)} · ${t('manage.reviews', { count: performer.rating_count })}`
      : t('manage.noReviews'),
    performer.district?.name ?? null,
  ]
    .filter(Boolean)
    .join(' · ');
  return (
    <Card as="article" tight aria-label={`${name}: ${price}`}>
      <div className="flex items-start gap-3">
        <Avatar name={name} src={avatar?.url} placeholder={performer.avatar?.placeholder} />
        <div className="flex min-w-0 grow flex-col gap-1">
          <div className="flex items-start justify-between gap-2">
            <span className="text-title">{name}</span>
            <Price>{price}</Price>
          </div>
          <Text as="span" variant="cap">
            {meta}
          </Text>
        </div>
      </div>
      <Text variant="sm" className="whitespace-pre-line">
        «{card.message}»
      </Text>
      {card.availability_note && (
        <p className="m-0 flex items-center gap-1.5 text-cap text-text2">
          <Icon name="calendar" size={16} className="shrink-0" />
          {card.availability_note}
        </p>
      )}
      <div className="flex flex-wrap gap-1.5">
        {card.is_new && (
          <Badge tone="info" dot>
            {t('manage.newResponse')}
          </Badge>
        )}
        {card.is_first && <Badge tone="ok">{t('manage.first')}</Badge>}
        {performer.phone_verified && <Badge tone="info">{t('manage.phone')}</Badge>}
        {performer.kind !== 'pro' && <Badge>{t('manage.casual')}</Badge>}
        {performer.kind === 'pro' && performer.is_new && (
          <Badge tone="info">{t('manage.newSpecialist')}</Badge>
        )}
      </div>
    </Card>
  );
}

function CloseSheet({
  onClose,
  onPick,
  busy,
}: {
  onClose: () => void;
  onPick: (reason: JobCloseInReason) => void;
  busy: boolean;
}) {
  const { t } = useTranslation('jobs');
  const { t: common } = useTranslation();
  useBackButton(onClose);
  return (
    <Sheet
      open
      title={t('manage.closeTitle')}
      onClose={onClose}
      closeLabel={common('action.close')}
    >
      <div className="flex flex-col gap-2">
        {REASONS.map((reason) => (
          <Button
            key={reason}
            variant="outline"
            full
            disabled={busy}
            onClick={() => onPick(reason)}
          >
            {t(`manage.reasons.${reason}`)}
          </Button>
        ))}
      </div>
    </Sheet>
  );
}

/** «Пригласите специалистов» шторкой (S23). */
function InviteSheet({ job, onClose }: { job: JobOut; onClose: () => void }) {
  const { t } = useTranslation('jobs');
  const { t: common } = useTranslation();
  const button = useBottomButtonState('main');
  useBackButton(onClose);
  return (
    <Sheet
      open
      title={t('manage.inviteTitle')}
      onClose={onClose}
      closeLabel={common('action.close')}
    >
      <Text variant="cap">{t('manage.inviteHint')}</Text>
      <InviteList job={job} />
      {!button.native && <div className="h-19" aria-hidden="true" />}
    </Sheet>
  );
}

/** Ошибка действия: 4xx — текстом сервера, остальное — «повторите». */
function ActionError({ error }: { error: unknown }) {
  const { t } = useTranslation('jobs');
  const detail = error instanceof ApiError && error.status < 500 ? error.problem.detail : null;
  return (
    <Banner tone="danger" role="alert">
      {detail ?? t('manage.error')}
    </Banner>
  );
}

function Loading() {
  return (
    <section className="flex flex-col gap-3.5 px-4 pt-3 pb-6" aria-busy="true">
      <Skeleton radius="card" className="h-56 w-full" />
      <Skeleton radius="card" className="h-32 w-full" />
    </section>
  );
}
