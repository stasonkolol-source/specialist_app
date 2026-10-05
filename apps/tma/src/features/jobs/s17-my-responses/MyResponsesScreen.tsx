// S17 Мои отклики (DEVELOPMENT_PLAN 5.5): сегмент вкладки «Заявки». Чипы «Все / Активные / Выбран
// / Не выбран / Архив» с числами (чип — в адресе, переживает «Назад»), «Сегодня откликов: 3 из 50 —
// лимит по уровню доверия», карточки новыми первыми: выбран — «Вас выбрали», ждёт решения —
// состояние, «На проверке» (клиент ещё не видит), «Первый отклик», места, «Открыть заявку»,
// «Изменить» (S16) и «Отозвать отклик» с подтверждением; не выбран и отозван — приглушённо, со
// временем решения. Иконка справа от заголовка — шаблоны S57. Отправленный с S16 — «клиент увидит
// его после проверки». Выбранного ждёт сделка: «Вас выбрали. Адрес и время — в сделке», главная
// кнопка — «Открыть сделку» (пока сделки грузятся — в загрузке), «Открыть заявку» — вторая.
import type { MyResponseOut, ResponseGroup, ResponseStatus } from '@sosed/api-client';
import { getSession } from '@sosed/api-client';
import { myResponseItems, useMyDeals, useMyResponses, useWithdrawResponse } from '@sosed/hooks';
import { useFormat, useTranslation } from '@sosed/i18n';
import { usePlatform } from '@sosed/platform';
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
  LinkButton,
  Price,
  ChipSkeleton,
  Skeleton,
  SkeletonCard,
  SkeletonText,
  Text,
} from '@sosed/ui-web';
import { useNavigate, useSearch } from '@tanstack/react-router';
import { useId } from 'react';

import { JobsSegments } from '../shared/JobsSegments.tsx';
import { LoadError } from '../shared/LoadError.tsx';
import { MiniSlots } from '../shared/MiniSlots.tsx';
import { useDistrictName, useOfferPrice } from '../shared/labels.ts';
import type { ResponsesSearch } from '../shared/paths.ts';
import { JOBS_PATHS, dealPath, jobPath, respondPath } from '../shared/paths.ts';

const GROUPS: readonly (ResponseGroup | null)[] = [
  null,
  'active',
  'accepted',
  'not_selected',
  'archive',
];
const ACTIVE: ReadonlySet<ResponseStatus> = new Set(['submitted', 'viewed', 'shortlisted']);

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
  const withdraw = useWithdrawResponse();
  const first = list.data?.pages[0];
  const items = myResponseItems(list.data);

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
      {first && (
        <p className="m-0 flex items-center gap-1.5 text-cap text-text2">
          <Icon name="info" size={16} className="shrink-0" />
          {t('responses.today', { used: first.today.used, limit: first.today.limit })}
        </p>
      )}
      {/* чипы групп с числами и лимит дня — из первой страницы: до неё их место держат скелетоны */}
      {!list.data && (
        <>
          <div aria-hidden="true" className="flex gap-2 overflow-hidden">
            {GROUPS.map((item) => (
              <ChipSkeleton key={item ?? 'all'} className="w-24" />
            ))}
          </div>
          <SkeletonText size="cap" screen className="w-1/2" />
        </>
      )}
      {sent && (
        <Banner tone="ok" role="status">
          {t('responses.sent')}
        </Banner>
      )}
      {withdraw.isError && (
        <Banner tone="danger" role="alert">
          {t('responses.withdrawError')}
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
            <ResponseCard
              key={response.id}
              response={response}
              withdrawing={withdraw.isPending && withdraw.variables?.responseId === response.id}
              onWithdraw={() =>
                withdraw.mutate({ jobId: response.job.id, responseId: response.id })
              }
            />
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
      <Skeleton radius="panel" className="mt-1 h-9 w-32" />
    </SkeletonCard>
  );
}

function ResponseCard({
  response,
  withdrawing,
  onWithdraw,
}: {
  response: MyResponseOut;
  withdrawing: boolean;
  onWithdraw: () => void;
}) {
  const { t } = useTranslation('jobs');
  const format = useFormat();
  const platform = usePlatform();
  const navigate = useNavigate();
  const offerPrice = useOfferPrice();
  const place = useDistrictName(response.job.city_id, response.job.district_id);
  const titleId = useId();
  const { status, job } = response;
  const active = ACTIVE.has(status);
  const accepted = status === 'accepted';
  const state = accepted ? t('responses.acceptedTitle') : t(`responses.state.${status}`);
  const price = offerPrice(response.price);
  const when = response.availability_note;
  const decided = response.decided_at ?? response.updated_at;
  const deals = useMyDeals({ role: 'performer' });
  const deal = accepted ? deals.data?.items.find((item) => item.response_id === response.id) : null;
  // у выбранного главная — сделка: пока список сделок грузится, кнопка ждёт на своём месте; сделки
  // не нашлось (не загрузилась) — главной становится «Открыть заявку»
  const dealButton = accepted && (deal !== undefined || deals.isPending);

  const confirmWithdraw = async () => {
    if (await platform.confirm(t('responses.withdrawConfirm'))) onWithdraw();
  };

  return (
    <Card as="article" tight aria-label={t('responses.card', { title: job.title, state })}>
      {accepted && (
        <Banner tone="ok">
          <b>{t('responses.acceptedLead')}</b> {t('responses.acceptedText')}
        </Banner>
      )}
      {active && (
        <div className="flex flex-wrap gap-1.5">
          <Badge tone="info">{state}</Badge>
          {response.review === 'pending' && <Badge tone="urgent">{t('responses.pending')}</Badge>}
          {response.review === 'blocked' && <Badge tone="danger">{t('responses.blocked')}</Badge>}
          {response.is_first && <Badge>{t('responses.first')}</Badge>}
        </div>
      )}
      {!active && !accepted && (
        <div className="flex items-center justify-between gap-3">
          <Badge>{state}</Badge>
          <Text as="span" variant="cap">
            {format.relative(new Date(decided))}
          </Text>
        </div>
      )}
      <div className="flex items-start justify-between gap-3">
        <h2 id={titleId} className={`m-0 text-title ${active || accepted ? '' : 'text-text2'}`}>
          {job.title}
        </h2>
        <Price className={active || accepted ? undefined : 'text-text2'}>{price}</Price>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1.5">
        <span className="flex min-w-0 items-center gap-1.5 text-cap text-text2">
          <Icon name="pin" size={16} className="shrink-0" />
          {/* у выбранного — и «когда смогу», как договорились; у остальных — только район */}
          <span>{[place, accepted ? when : null].filter(Boolean).join(' · ')}</span>
        </span>
        {active && <MiniSlots job={job} />}
      </div>
      {(active || accepted) && (
        <div className="mt-1 flex flex-wrap items-center gap-2">
          {dealButton && (
            <Button
              size="sm"
              aria-describedby={titleId}
              disabled={!deal}
              aria-busy={!deal}
              onClick={() => deal && void navigate({ to: dealPath(deal.id) })}
            >
              {t('responses.openDeal')}
            </Button>
          )}
          <Button
            variant={accepted && !dealButton ? 'primary' : 'outline'}
            size="sm"
            aria-describedby={titleId}
            onClick={() => void navigate({ to: jobPath(job.id) })}
          >
            {t('responses.open')}
          </Button>
          {active && (
            <>
              <Button
                variant="outline"
                size="sm"
                aria-describedby={titleId}
                onClick={() => void navigate({ to: respondPath(job.id) })}
              >
                {t('responses.edit')}
              </Button>
              <LinkButton
                danger
                aria-describedby={titleId}
                disabled={withdrawing}
                aria-busy={withdrawing}
                onClick={() => void confirmWithdraw()}
              >
                {t('responses.withdraw')}
              </LinkButton>
            </>
          )}
        </div>
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
