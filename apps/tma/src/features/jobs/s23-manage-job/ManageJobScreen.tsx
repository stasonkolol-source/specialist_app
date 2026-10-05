// S23 Своя заявка (DEVELOPMENT_PLAN 5.6; UX_GUIDANCE №5, №13): строка статуса словом словаря и
// пояснением рядом — «На проверке · обычно несколько минут», «Ждём откликов · открыта до 12
// октября», «3 отклика — выберите исполнителя», «Нужно исправить» с причиной модерации; баннер её
// не повторяет. Дальше «когда», район («точный адрес откроется выбранному»), бюджет, просмотры и
// полоска «3 из 5 откликов» («осталось N мест» — язык исполнителя, клиенту его нет). «Пригласить» —
// шторка с подходящими специалистами из каталога (категория и город заявки), «Продлить» — когда
// срок на исходе или вышел, «Поднять» — v1 (до него кнопки нет). Откликов нет — «бот напишет о
// первом» и одна кнопка «Пригласить специалистов». Отклики — карточками по времени отклика: фото и
// имя (непросмотренный — точкой), рейтинг со звездой или «Новый специалист», район, цена, сообщение
// и не больше двух бейджей: «Откликнулся первым», «Телефон подтверждён», «Подработка»; опрос раз в
// 15 секунд — вместе с самой заявкой: места и просмотры в шапке не отстают от списка. Заявка
// перечитывается и при каждом открытии, а на проверке — чаще: из «на проверке» экран сам переходит
// в «Ждём откликов» или «Нужно исправить». «Закрыть заявку» спрашивает причину. «Изменить» — мастер
// S20a–d с этой заявкой (`?edit=<id>`, сохранение с If-Match). Карточка отклика ведёт на S24 —
// выбрать исполнителя или отклонить (6.2). Выбор сделан или приём закрыт — итог вместо процесса:
// «В работе · Илья И.» и «Открыть сделку» (S26); «Выполнена 5 октября · Илья И. · 6 500 RSD» и одно
// действие — «Оставить отзыв» или «Заказать снова»; «Закрыта …», «Срок истёк …»; счётчиков, мест и
// подсказки про адрес нет, отклики свёрнуты в «Отклики (N)». «Поделиться» (7.4) — у опубликованной
// заявки не прямым запросом: карточка в выбор чата Telegram или ссылка. Из «Моих заявок» S22 экран
// рисуется сразу — заявкой из списка, отклики грузятся вместе с ней.
import type { JobCloseInReason, JobOut, ResponseCardOut } from '@sosed/api-client';
import { ApiError, getSession } from '@sosed/api-client';
import {
  isUnavailable,
  useCloseJob,
  useDealCard,
  useExtendJob,
  useMyDeals,
  useOwnJob,
  useResponseCards,
  useStartConversation,
} from '@sosed/hooks';
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
  SkeletonText,
  Text,
  UnreadDot,
} from '@sosed/ui-web';
import { Navigate, useParams, useRouter } from '@tanstack/react-router';
import { useId, useState } from 'react';

import { useBotChannel } from '../shared/BotChannel.tsx';
import { InviteList } from '../shared/InviteList.tsx';
import { JobUnavailable } from '../shared/JobUnavailable.tsx';
import { useDraftStore } from '../shared/draft.ts';
import { LoadError } from '../shared/LoadError.tsx';
import { PerformerRating } from '../shared/PerformerRating.tsx';
import { useBudgetText, useDistrictName, useOfferPrice, useWhenBadge } from '../shared/labels.ts';
import { shareable, useJobShare } from '../shared/share.tsx';
import { JobSummarySkeleton, OfferCardSkeleton } from '../shared/skeletons.tsx';
import {
  CREATE_PATHS,
  JOBS_PATHS,
  chatPath,
  choicePath,
  dealPath,
  jobIdOf,
  jobPath,
  reviewPath,
} from '../shared/paths.ts';

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
/** Заявка ещё собирает отклики (или ждёт проверки): счётчики, места и отклики списком. */
const OPEN: ReadonlySet<JobOut['status']> = new Set([
  'published',
  'pending_moderation',
  'rejected',
]);
/** Исполнитель выбран: итог и действие — по сделке. */
const DEAL_STATES: ReadonlySet<JobOut['status']> = new Set(['assigned', 'completed']);

export function ManageJobScreen() {
  const { jobId: raw = '' } = useParams({ strict: false });
  const jobId = jobIdOf(raw);
  const job = useOwnJob(jobId);
  // отклики — вместе с заявкой, а не после неё; чужая заявка (уйдёт на S15) получит отказ
  // сервера, гостю своих заявок нет
  useResponseCards(getSession() !== null ? jobId : null);
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
  const sharing = useJobShare(job.id);
  const published = job.status === 'published';
  const items = cards.data?.items ?? [];
  // откликов нет — «Пригласить специалистов» одной кнопкой в пустом состоянии, а не ещё и в шапке
  const empty = published && cards.data !== undefined && items.length === 0;
  const failed = close.error ?? extend.error;
  const summary = {
    job,
    onEdit: () => {
      // правка — всегда с версии, которую видно сейчас; мастер заменяет запись S23 и
      // возвращается на неё же: «Назад» после сохранения не ведёт по шагам правки
      useDraftStore.getState().edit(job);
      void router.navigate({ to: CREATE_PATHS.what, search: { edit: job.id }, replace: true });
    },
    onInvite: empty ? undefined : () => setInviting(true),
    onShare: shareable(job) ? sharing.share : undefined,
    sharing: sharing.pending,
    onExtend: () => extend.mutate(job.id),
    extending: extend.isPending,
  };

  return (
    <section className="flex flex-col gap-3.5 px-4 pt-3 pb-6">
      {DEAL_STATES.has(job.status) ? <DealSummary {...summary} /> : <Summary {...summary} />}
      {failed && <ActionError error={failed} />}
      {job.status === 'rejected' && (
        <Banner tone="danger" role="status">
          {t('manage.rejected', { reason: job.moderation_note ?? '' })}
        </Banner>
      )}
      {OPEN.has(job.status) ? (
        <Responses job={job} cards={cards} onInvite={empty ? () => setInviting(true) : undefined} />
      ) : (
        <PastResponses job={job} items={items} />
      )}
      {(published ||
        job.status === 'pending_moderation' ||
        job.status === 'rejected' ||
        job.status === 'expired') && (
        <Group>
          <Row
            danger
            title={t('manage.close')}
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
      {sharing.notice}
    </section>
  );
}

/** Отклики открытой заявки по времени отклика. Пока их нет — что будет дальше и одна кнопка
 *  (UX_GUIDANCE №5): бот напишет о первом (если ему можно писать), а быстрее — пригласить. */
function Responses({
  job,
  cards,
  onInvite,
}: {
  job: JobOut;
  cards: ReturnType<typeof useResponseCards>;
  /** Есть — пустое состояние с «Пригласить специалистов». */
  onInvite: (() => void) | undefined;
}) {
  const { t } = useTranslation('jobs');
  const bot = useBotChannel();
  const responsesId = useId();
  const items = cards.data?.items ?? [];
  return (
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
        <OfferCardSkeleton />
      ) : items.length === 0 ? (
        <EmptyState
          as="h3"
          icon="send"
          title={t('manage.noResponsesTitle')}
          action={
            onInvite && (
              <Button variant="secondary" icon="users" onClick={onInvite}>
                {t('manage.inviteAction')}
              </Button>
            )
          }
        >
          {onInvite && bot.writable !== null
            ? t(bot.writable ? 'manage.noResponsesText' : 'manage.noResponsesApp')
            : null}
        </EmptyState>
      ) : (
        items.map((card) => <ResponseCard key={card.id} jobId={job.id} card={card} />)
      )}
    </section>
  );
}

/** Выбор сделан или приём закрыт: отклики свёрнуты в «Отклики (N)» — итог важнее процесса. */
function PastResponses({ job, items }: { job: JobOut; items: ResponseCardOut[] }) {
  const { t } = useTranslation('jobs');
  const [expanded, setExpanded] = useState(false);
  if (items.length === 0) return null;
  return (
    <section className="flex flex-col gap-2.5" aria-label={t('manage.responses')}>
      <Group>
        <Row
          title={t('manage.responsesCount', { count: items.length })}
          expanded={expanded}
          onClick={() => setExpanded(!expanded)}
        />
      </Group>
      {expanded && items.map((card) => <ResponseCard key={card.id} jobId={job.id} card={card} />)}
    </section>
  );
}

interface SummaryProps {
  job: JobOut;
  onEdit: () => void;
  /** Нет — «Пригласить» в шапке не нужна (заявка не открыта или кнопка — в пустом состоянии). */
  onInvite: (() => void) | undefined;
  /** Нет — заявкой делиться нельзя (не опубликована или прямой запрос). */
  onShare: (() => void) | undefined;
  sharing: boolean;
  onExtend: () => void;
  extending: boolean;
}

/** Строка статуса — одним словом словаря (UX_GUIDANCE, приложение) и пояснением рядом: сколько
 *  ждать, до какого числа открыта, с кем и за сколько сделано. Баннер её не повторяет. */
function StatusRow({
  word,
  tone = 'mute',
  dot = false,
  note,
}: {
  word: string;
  tone?: 'ok' | 'danger' | 'mute';
  dot?: boolean;
  note?: string | null;
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-2">
      <Badge tone={tone} dot={dot}>
        {word}
      </Badge>
      {note && (
        <Text as="span" variant="cap">
          {note}
        </Text>
      )}
    </div>
  );
}

/** Карточка заявки без сделки: статус, «когда», район, бюджет, места, просмотры и действия.
 *  Счётчики, места и подсказка про адрес — пока заявка открыта; закрытая и истёкшая — итог. */
function Summary({ job, onEdit, onInvite, onShare, sharing, onExtend, extending }: SummaryProps) {
  const { t } = useTranslation('jobs');
  const { t: common } = useTranslation();
  const format = useFormat();
  const titleId = useId();
  const published = job.status === 'published';
  const expires = job.expires_at ? new Date(job.expires_at).getTime() : null;
  // «скоро истечёт» — от момента открытия экрана
  const [now] = useState(() => Date.now());
  const canExtend =
    job.extensions_count < MAX_EXTENSIONS &&
    (job.status === 'expired' || (published && expires !== null && expires - now < DAY_MS));
  const date = (value: string) => format.dateGenitive(new Date(value));
  const status = (() => {
    switch (job.status) {
      case 'published':
        return (
          <StatusRow
            tone="ok"
            dot
            word={
              job.responses_count > 0
                ? t('mine.responses', { count: job.responses_count })
                : t('mine.status.published')
            }
            note={job.expires_at ? t('manage.openUntil', { date: date(job.expires_at) }) : null}
          />
        );
      case 'pending_moderation':
        return (
          <StatusRow word={t('mine.status.pending_moderation')} note={t('manage.reviewNote')} />
        );
      case 'rejected':
        return <StatusRow tone="danger" word={t('mine.status.rejected')} />;
      case 'closed':
        return (
          <StatusRow
            word={
              job.closed_at
                ? t('mine.closedOn', { date: date(job.closed_at) })
                : t('mine.status.closed')
            }
          />
        );
      case 'expired':
        return (
          <StatusRow
            word={
              job.expires_at
                ? t('mine.expiredOn', { date: date(job.expires_at) })
                : t('mine.status.expired')
            }
          />
        );
      default:
        return <StatusRow word={t(`mine.status.${job.status}`)} />;
    }
  })();
  return (
    <Card as="section" aria-labelledby={titleId}>
      {status}
      <Heading variant="h2" as="h1" id={titleId}>
        {job.title}
      </Heading>
      <JobFacts job={job} />
      {published && job.responses_count > 0 && <Slots job={job} />}
      <div className="grid grid-cols-2 gap-2">
        {EDITABLE.has(job.status) && (
          <Button variant="outline" icon="edit" onClick={onEdit}>
            {t('manage.edit')}
          </Button>
        )}
        {published && onInvite && (
          <Button variant="outline" icon="users" onClick={onInvite}>
            {t('manage.invite')}
          </Button>
        )}
        {onShare && (
          <Button variant="outline" icon="share" aria-busy={sharing} onClick={onShare}>
            {common('action.share')}
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
        {/* «Поднять» (`manage.raise`) — v1: до него кнопки нет, метка версии в интерфейсе не нужна */}
      </div>
    </Card>
  );
}

/** «Когда», район и бюджет. Пока заявка открыта, у района — подсказка про точный адрес; у
 *  выполненной «когда» и бюджет уже не нужны: итог — в строке статуса. */
function JobFacts({ job }: { job: JobOut }) {
  const { t } = useTranslation('jobs');
  const { t: common } = useTranslation();
  const whenBadge = useWhenBadge();
  const budgetText = useBudgetText();
  const place = useDistrictName(job.city_id, job.district_id);
  const open = OPEN.has(job.status);
  const done = job.status === 'completed';
  const budget = budgetText(job, { unit: false });
  const unit = common(`unit.${job.budget_unit}`);
  const kind = job.budget_type === 'negotiable' ? null : t(`manage.budgetTypes.${job.budget_type}`);
  return (
    <div className="flex flex-col gap-2 text-cap text-text2">
      {!done && (
        <p className="m-0 flex items-center gap-1.5">
          <Icon name="clock" size={16} className="shrink-0" />
          {whenBadge(job, true).label}
        </p>
      )}
      {place && (
        <p className="m-0 flex items-center gap-1.5">
          <Icon name="pin" size={16} className="shrink-0" />
          {open ? t('manage.place', { place }) : place}
        </p>
      )}
      {!done && (
        <p className="m-0 flex items-center gap-1.5">
          <Icon name="wallet" size={16} className="shrink-0" />
          {budget
            ? [budget, [kind, unit].filter(Boolean).join(', ')].join(' · ')
            : t('card.negotiable')}
        </p>
      )}
      {open && job.views_count !== null && (
        <p className="m-0 flex items-center gap-1.5">
          <Icon name="eye" size={16} className="shrink-0" />
          {t('manage.views', { count: job.views_count })}
        </p>
      )}
    </div>
  );
}

/** Полоска «3 из 5 откликов»: сколько уже пришло. «Осталось N мест» — язык исполнителя, клиенту
 *  его не показываем. */
function Slots({ job }: { job: JobOut }) {
  const { t } = useTranslation('jobs');
  return (
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
        {t('manage.slotsRest')}
      </span>
    </div>
  );
}

/** Заявка со сделкой: «В работе · Илья И.» и «Открыть сделку»; выполненная — итог одной строкой
 *  «Выполнена 5 октября · Илья И. · 6 500 RSD» и одно действие (UX_GUIDANCE №13): «Оставить
 *  отзыв», пока его можно оставить, потом — «Заказать снова» (прямой диалог, как на S26). */
function DealSummary({ job }: SummaryProps) {
  const { t } = useTranslation('jobs');
  const { t: common } = useTranslation();
  const format = useFormat();
  const router = useRouter();
  const offerPrice = useOfferPrice();
  const titleId = useId();
  const deals = useMyDeals({ role: 'client' });
  const deal = deals.data?.items.find((item) => item.job_id === job.id) ?? null;
  const card = useDealCard(deal?.id ?? null).data;
  const start = useStartConversation();
  const done = job.status === 'completed';
  const name = card?.counterpart.display_name || null;
  const price =
    deal && deal.price.type !== null && deal.price.type !== 'negotiable'
      ? offerPrice({ type: deal.price.type, amount: deal.price.amount })
      : null;
  const ended = job.closed_at ?? deal?.completed_at ?? null;
  const word = done
    ? ended
      ? t('mine.completedOn', { date: format.dateGenitive(new Date(ended)) })
      : t('mine.status.completed')
    : t('mine.status.assigned');
  const reviewing = done && card !== undefined && card.review_until !== null && !card.my_review;
  const action = (() => {
    if (!deal) return null;
    if (reviewing) {
      return (
        <Button
          variant="secondary"
          full
          onClick={() => void router.navigate({ to: reviewPath(deal.id) })}
        >
          {common('action.leaveReview')}
        </Button>
      );
    }
    if (done && card && deal.profile_id) {
      const profileId = deal.profile_id;
      return (
        <Button
          variant="secondary"
          full
          disabled={start.isPending}
          aria-busy={start.isPending}
          onClick={() =>
            start.mutate(
              { profile_id: profileId },
              { onSuccess: (started) => void router.navigate({ to: chatPath(started.id) }) },
            )
          }
        >
          {t('deal.orderAgain')}
        </Button>
      );
    }
    return (
      <Button
        variant="secondary"
        full
        onClick={() => void router.navigate({ to: dealPath(deal.id) })}
      >
        {t('manage.openDeal')}
      </Button>
    );
  })();
  return (
    <Card as="section" aria-labelledby={titleId}>
      <StatusRow
        tone={done ? 'mute' : 'ok'}
        word={word}
        note={[name, done ? price : null].filter(Boolean).join(' · ') || null}
      />
      <Heading variant="h2" as="h1" id={titleId}>
        {job.title}
      </Heading>
      <JobFacts job={job} />
      {action}
      {start.error && <ActionError error={start.error} />}
    </Card>
  );
}
/** Отклик: исполнитель, цена, сообщение и бейджи; непросмотренный — точкой у имени. Выбор
 *  исполнителя (S24) — 6.2. */
function ResponseCard({ jobId, card }: { jobId: string; card: ResponseCardOut }) {
  const { t } = useTranslation('jobs');
  const router = useRouter();
  const offerPrice = useOfferPrice();
  const to = choicePath(jobId, card.id);
  const { performer } = card;
  const name = performer.display_name || '—';
  const avatar =
    performer.avatar?.variants.find((v) => v.name === 'thumb') ?? performer.avatar?.variants[0];
  const price = card.price.type === 'negotiable' ? t('card.negotiable') : offerPrice(card.price);
  const casual = performer.kind !== 'pro';
  // не больше двух бейджей в строке: «Откликнулся первым» уступает фактам об исполнителе
  const first = card.is_first && !(casual && performer.phone_verified);
  return (
    <Card
      tight
      aria-label={`${name}: ${price}`}
      href={router.history.createHref(to)}
      onClick={(event) => {
        event.preventDefault();
        void router.navigate({ to });
      }}
    >
      <div className="flex items-start gap-3">
        <Avatar name={name} src={avatar?.url} placeholder={performer.avatar?.placeholder} />
        <div className="flex min-w-0 grow flex-col gap-1">
          <div className="flex items-start justify-between gap-2">
            <Name name={name} unread={card.is_new ? t('manage.newResponse') : null} />
            <Price>{price}</Price>
          </div>
          {/* «Новый специалист» — в строке рейтинга, отдельным бейджем не повторяем */}
          <PerformerRating
            rating={performer.rating}
            count={performer.rating_count}
            meta={[performer.district?.name]}
          />
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
      {(first || performer.phone_verified || casual) && (
        <div className="flex flex-wrap gap-1.5">
          {first && <Badge tone="ok">{t('manage.first')}</Badge>}
          {performer.phone_verified && (
            <Badge tone="info" icon="shield">
              {t('manage.phone')}
            </Badge>
          )}
          {casual && <Badge>{t('manage.casual')}</Badge>}
        </div>
      )}
    </Card>
  );
}

/** Имя исполнителя; непросмотренный отклик — точкой сразу за последним словом: имя не
 *  переносится из-за точки раньше времени, а при переносе точка уходит вместе с этим словом. */
function Name({ name, unread }: { name: string; unread: string | null }) {
  if (!unread) return <span className="text-title">{name}</span>;
  const last = name.lastIndexOf(' ') + 1;
  return (
    <span className="text-title">
      {name.slice(0, last)}
      {/* пробел перед точкой (в nowrap не переносится) — отступ и граница слов для скринридера;
          точка 8 px стоит на базовой линии — её середина на высоте строчных букв */}
      <span className="whitespace-nowrap">
        {name.slice(last)} <UnreadDot label={unread} />
      </span>
    </span>
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
      <JobSummarySkeleton />
      <SkeletonText size="h3" screen className="w-1/3" />
      <OfferCardSkeleton />
    </section>
  );
}
