// S17 Мои отклики (DEVELOPMENT_PLAN 5.5): сегмент вкладки «Заявки». Чипы «Все / Активные / Выбран
// / Не выбран / Архив» с числами (чип — в адресе, переживает «Назад»), карточки новыми первыми. У
// карточки один статус словами исполнителя (UX №10): «Ждёт решения клиента», «На проверке» (только
// пока проверка правда идёт), «Не прошёл проверку», «Срок заявки истёк», «Вас выбрали. Адрес и время
// — в сделке», «Выполнено», «Выбрали другого», «Заявка закрыта без выбора», «Клиент отклонил», «Вы
// отозвали» — и одна кнопка: выбранному — «Открыть сделку» (пока сделки грузятся — в загрузке, не
// нашлась — «Открыть заявку»), ждущему решения — «Открыть заявку»; «Изменить отклик» и «Отозвать»
// живут на S15 → S16. Квота дня — только у предела (осталось не больше 20 %). Отправленный с S16 —
// что подтвердил сервер: пока автопроверка не ответила, список перечитывается (UX №1). Иконка справа
// от заголовка — шаблоны S57.
import type {
  JobStatus,
  MyResponseOut,
  ResponseGroup,
  ResponseStatus,
  TodayOut,
} from '@sosed/api-client';
import { getSession } from '@sosed/api-client';
import { myResponseItems, useMyDeals, useMyResponses } from '@sosed/hooks';
import { useFormat, useTranslation } from '@sosed/i18n';
import type { BadgeTone } from '@sosed/ui-web';
import {
  Badge,
  Banner,
  Button,
  Card,
  Chip,
  Chips,
  EmptyState,
  Heading,
  Icon,
  IconButton,
  Price,
  ChipSkeleton,
  Skeleton,
  SkeletonCard,
  SkeletonText,
  Text,
} from '@sosed/ui-web';
import { useNavigate, useSearch } from '@tanstack/react-router';
import { useEffect, useId, useState } from 'react';

import { JobsSegments } from '../shared/JobsSegments.tsx';
import { LoadError } from '../shared/LoadError.tsx';
import { MiniSlots } from '../shared/MiniSlots.tsx';
import { useDistrictName, useOfferPrice } from '../shared/labels.ts';
import type { ResponsesSearch } from '../shared/paths.ts';
import { JOBS_PATHS, dealPath, jobPath } from '../shared/paths.ts';

const GROUPS: readonly (ResponseGroup | null)[] = [
  null,
  'active',
  'accepted',
  'not_selected',
  'archive',
];
const ACTIVE: ReadonlySet<ResponseStatus> = new Set(['submitted', 'viewed', 'shortlisted']);
/** Заявка закрыта клиентом или снята модерацией — выбора не было (MU-11). */
const CLOSED_JOB: ReadonlySet<JobStatus> = new Set(['closed', 'removed']);

/** Исход отклика — одно слово на состояние, как в боте (словарь статусов UX_GUIDANCE). */
type Outcome =
  | 'waiting'
  | 'pending'
  | 'blocked'
  | 'expired'
  | 'accepted'
  | 'completed'
  | 'not_selected'
  | 'job_closed'
  | 'declined'
  | 'withdrawn';

function outcomeOf({ status, review, job }: MyResponseOut): Outcome {
  if (ACTIVE.has(status)) {
    if (review === 'blocked') return 'blocked';
    if (review === 'pending') return 'pending';
    return job.status === 'expired' ? 'expired' : 'waiting';
  }
  if (status === 'accepted') return job.status === 'completed' ? 'completed' : 'accepted';
  if (status === 'not_selected') return CLOSED_JOB.has(job.status) ? 'job_closed' : 'not_selected';
  return status === 'declined' ? 'declined' : 'withdrawn';
}

const TONES: Record<Outcome, BadgeTone> = {
  waiting: 'info',
  pending: 'urgent',
  blocked: 'danger',
  expired: 'mute',
  accepted: 'ok',
  completed: 'ok',
  not_selected: 'mute',
  job_closed: 'mute',
  declined: 'mute',
  withdrawn: 'mute',
};
/** Решено клиентом или исполнителем — со временем решения. */
const DECIDED: ReadonlySet<Outcome> = new Set([
  'not_selected',
  'job_closed',
  'declined',
  'withdrawn',
]);

/** Квота дня — только у предела: осталось не больше 20 % (UX, принцип 7). */
const QUOTA_NEAR = 0.2;
const leftToday = (today: TodayOut) => Math.max(today.limit - today.used, 0);
const nearLimit = (today: TodayOut) => leftToday(today) <= today.limit * QUOTA_NEAR;

/** Пока автопроверка только что отправленного не ответила — перечитываем каждые 2,5 с, не дольше
 *  30 с; дальше честно «после проверки» (UX, принцип 1). */
const SENT_POLL_MS = 2_500;
const SENT_POLL_LIMIT_MS = 30_000;

/** Отправленный с S16 — последний изменённый из ждущих решения: новый или только что поправленный. */
function latest(items: readonly MyResponseOut[]): MyResponseOut | undefined {
  return items
    .filter((item) => ACTIVE.has(item.status))
    .reduce<MyResponseOut | undefined>(
      (best, item) => (!best || item.updated_at > best.updated_at ? item : best),
      undefined,
    );
}

function useSentPolling(checking: boolean, refetch: () => Promise<unknown>) {
  const [polling, setPolling] = useState(true);
  useEffect(() => {
    const stop = setTimeout(() => setPolling(false), SENT_POLL_LIMIT_MS);
    return () => clearTimeout(stop);
  }, []);
  useEffect(() => {
    if (!polling || !checking) return;
    const timer = setInterval(() => void refetch(), SENT_POLL_MS);
    return () => clearInterval(timer);
  }, [polling, checking, refetch]);
}

export function MyResponsesScreen() {
  const { t } = useTranslation('jobs');
  const search: ResponsesSearch = useSearch({ strict: false });
  const navigate = useNavigate();
  const group = search.status ?? null;
  const signedIn = getSession() !== null;

  return (
    <section className="flex flex-col gap-3 px-4 pt-3 pb-6">
      <JobsSegments current="responses" />
      <div className="flex items-center justify-between gap-3">
        <Heading variant="h1">{t('segments.responses')}</Heading>
        {signedIn && (
          <IconButton
            icon="file"
            label={t('responses.templates')}
            onClick={() => void navigate({ to: JOBS_PATHS.templates })}
          />
        )}
      </div>
      {signedIn ? (
        <Responses
          group={group}
          sent={search.sent === true}
          onGroup={(next) =>
            void navigate({
              to: JOBS_PATHS.responses,
              search: next ? { status: next } : {},
              replace: true,
            })
          }
        />
      ) : (
        <Empty group={null} />
      )}
    </section>
  );
}

function Responses({
  group,
  sent,
  onGroup,
}: {
  group: ResponseGroup | null;
  sent: boolean;
  onGroup: (group: ResponseGroup | null) => void;
}) {
  const { t } = useTranslation('jobs');
  const list = useMyResponses(group);
  const first = list.data?.pages[0];
  const items = myResponseItems(list.data);
  const fresh = sent ? latest(items) : undefined;
  useSentPolling(fresh?.review === 'pending', list.refetch);

  if (list.isError && !list.data) {
    return (
      <LoadError
        error={list.error}
        onRetry={() => void list.refetch()}
        retrying={list.isRefetching}
      />
    );
  }
  return (
    <>
      {first && (
        <Chips label={t('responses.groupsLabel')}>
          {GROUPS.map((item) => {
            const count = first.counts[item ?? 'all'];
            const label = t(`responses.groups.${item ?? 'all'}`);
            return (
              <Chip key={item ?? 'all'} selected={item === group} onClick={() => onGroup(item)}>
                {count > 0 ? `${label} ${count}` : label}
              </Chip>
            );
          })}
        </Chips>
      )}
      {first && nearLimit(first.today) && (
        <p className="m-0 flex items-center gap-1.5 text-cap text-text2">
          <Icon name="info" size={16} className="shrink-0" />
          {t('responses.today', { left: leftToday(first.today) })}
        </p>
      )}
      {/* чипы групп с числами — из первой страницы: до неё их место держат скелетоны */}
      {!list.data && (
        <div aria-hidden="true" className="flex gap-2 overflow-hidden">
          {GROUPS.map((item) => (
            <ChipSkeleton key={item ?? 'all'} className="w-24" />
          ))}
        </div>
      )}
      {/* скрытый модератором сразу — об этом скажет его карточка, «отправлен» был бы неправдой */}
      {fresh && fresh.review !== 'blocked' && (
        <Banner tone="ok" role="status">
          {t(fresh.review === 'pending' ? 'responses.sentPending' : 'responses.sent')}
        </Banner>
      )}
      {!list.data ? (
        <div aria-busy="true" className="flex flex-col gap-3">
          <ResponseCardSkeleton />
          <ResponseCardSkeleton />
        </div>
      ) : items.length === 0 ? (
        <Empty group={group} />
      ) : (
        <>
          {items.map((response) => (
            <ResponseCard key={response.id} response={response} />
          ))}
          {list.hasNextPage && (
            <Button
              variant="outline"
              full
              disabled={list.isFetchingNextPage}
              aria-busy={list.isFetchingNextPage}
              onClick={() => void list.fetchNextPage()}
            >
              {t('responses.more')}
            </Button>
          )}
        </>
      )}
    </>
  );
}

/** Отклик, пока не пришёл: статус, заявка и цена, место, действия. */
function ResponseCardSkeleton() {
  return (
    <SkeletonCard tight>
      <Skeleton className="h-6 w-28" />
      <div className="flex items-start justify-between gap-3">
        <SkeletonText size="title" className="w-3/5" />
        <SkeletonText size="title" className="w-20" />
      </div>
      <SkeletonText size="cap" className="w-1/2" />
      <Skeleton radius="icon" className="mt-1 h-9 w-32" />
    </SkeletonCard>
  );
}

function ResponseCard({ response }: { response: MyResponseOut }) {
  const { t } = useTranslation('jobs');
  const format = useFormat();
  const navigate = useNavigate();
  const offerPrice = useOfferPrice();
  const place = useDistrictName(response.job.city_id, response.job.district_id);
  const titleId = useId();
  const { job } = response;
  const outcome = outcomeOf(response);
  const state = t(`responses.outcome.${outcome}`);
  const waiting = ACTIVE.has(response.status) && outcome !== 'expired';
  const accepted = response.status === 'accepted';
  // ждёт решения или выбран — яркая карточка; остальные исходы — приглушённо
  const live = waiting || outcome === 'accepted';
  const price = offerPrice(response.price);
  const when = response.availability_note;
  const decided = response.decided_at ?? response.updated_at;
  const deals = useMyDeals({ role: 'performer' });
  const deal = accepted ? deals.data?.items.find((item) => item.response_id === response.id) : null;
  // у выбранного кнопка — сделка: пока список сделок грузится, она ждёт на своём месте; сделки не
  // нашлось (не загрузилась) — вместо неё «Открыть заявку»
  const dealButton = accepted && (deal !== undefined || deals.isPending);

  return (
    <Card as="article" tight aria-label={t('responses.card', { title: job.title, state })}>
      {outcome === 'accepted' ? (
        <Banner tone="ok">
          <b>{t('responses.acceptedLead')}</b> {t('responses.acceptedText')}
        </Banner>
      ) : (
        <div className="flex items-center justify-between gap-3">
          <Badge tone={TONES[outcome]}>{state}</Badge>
          {DECIDED.has(outcome) && (
            <Text as="span" variant="cap">
              {format.relative(new Date(decided))}
            </Text>
          )}
        </div>
      )}
      <div className="flex items-start justify-between gap-3">
        <h2 id={titleId} className={`m-0 text-title ${live ? '' : 'text-text2'}`}>
          {job.title}
        </h2>
        <Price className={live ? undefined : 'text-text2'}>{price}</Price>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1.5">
        <span className="flex min-w-0 items-center gap-1.5 text-cap text-text2">
          <Icon name="pin" size={16} className="shrink-0" />
          {/* у выбранного — и «когда смогу», как договорились; у остальных — только район */}
          <span>{[place, accepted ? when : null].filter(Boolean).join(' · ')}</span>
        </span>
        {waiting && <MiniSlots job={job} />}
      </div>
      {dealButton ? (
        <Button
          size="sm"
          className="mt-1 self-start"
          aria-describedby={titleId}
          disabled={!deal}
          aria-busy={!deal}
          onClick={() => deal && void navigate({ to: dealPath(deal.id) })}
        >
          {t('responses.openDeal')}
        </Button>
      ) : (
        (ACTIVE.has(response.status) || accepted) && (
          <Button
            variant={accepted ? 'primary' : 'outline'}
            size="sm"
            className="mt-1 self-start"
            aria-describedby={titleId}
            onClick={() => void navigate({ to: jobPath(job.id) })}
          >
            {t('responses.open')}
          </Button>
        )
      )}
    </Card>
  );
}

function Empty({ group }: { group: ResponseGroup | null }) {
  const { t } = useTranslation('jobs');
  const navigate = useNavigate();
  return group === null ? (
    <EmptyState
      as="h2"
      icon="send"
      title={t('responses.emptyTitle')}
      action={
        <Button variant="secondary" onClick={() => void navigate({ to: JOBS_PATHS.feed })}>
          {t('responses.toFeed')}
        </Button>
      }
    >
      {t('responses.emptyText')}
    </EmptyState>
  ) : (
    <EmptyState as="h2" icon="send" title={t('responses.emptyGroup')} />
  );
}
