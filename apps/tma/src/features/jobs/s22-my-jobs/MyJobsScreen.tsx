// S22 Мои заявки (DEVELOPMENT_PLAN 5.6): сегмент вкладки «Заявки». Заявки разделами «Активные / В
// работе / Завершённые / Архив»; чипы-фильтры «Все / Активные / …» — только от пяти заявок: при
// одной-двух они лишь занимают место (UX_GUIDANCE §5). «+» — новая заявка S20a. В группе первыми —
// заявки, где ждут выбора исполнителя (order.ts). Карточка — как в ленте: название и бюджет,
// «когда» и категория, район и время, места «откликов 3 из 5» или «Ждём откликов» своей строкой;
// есть отклики — «3 отклика — выберите исполнителя» и «2 новых», пока клиент их не открыл; на
// проверке, нужно исправить — словами; итог — словом словаря с датой: «Выполнена 5 октября»,
// «Закрыта 14 сентября», «Срок истёк …»; «В работе» — без даты. Нажатие — своя заявка S23.
// Бейдж «Заявки» знает о новом отклике раньше списка (опрос раз в минуту, список — из кэша):
// список перечитывается, и «N новых» появляется на карточке той заявки.
import type { JobOut, JobStatus } from '@sosed/api-client';
import { getSession } from '@sosed/api-client';
import { useBadges, useCategories, useMyJobs } from '@sosed/hooks';
import { useFormat, useLocale, useTranslation } from '@sosed/i18n';
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
  JobCardSkeleton,
  Price,
  SectionTitle,
  SkeletonText,
  Text,
} from '@sosed/ui-web';
import { useNavigate, useRouter } from '@tanstack/react-router';
import { useEffect, useState } from 'react';

import { JobsSegments } from '../shared/JobsSegments.tsx';
import { LoadError } from '../shared/LoadError.tsx';
import { MiniSlots } from '../shared/MiniSlots.tsx';
import { findCategory } from '../shared/categories.ts';
import { useBudgetText, useDistrictName, useWhenBadge } from '../shared/labels.ts';
import { CREATE_PATHS, managePath } from '../shared/paths.ts';
import { byAttention } from './order.ts';

type Group = 'active' | 'work' | 'done' | 'archive';
const GROUPS: readonly Group[] = ['active', 'work', 'done', 'archive'];
/** С какого числа заявок нужны чипы-фильтры. */
const FILTERS_FROM = 5;
const GROUP_OF: Record<JobStatus, Group> = {
  draft: 'active',
  pending_moderation: 'active',
  published: 'active',
  rejected: 'active',
  assigned: 'work',
  completed: 'done',
  closed: 'archive',
  expired: 'archive',
  removed: 'archive',
};

export function MyJobsScreen() {
  const { t } = useTranslation('jobs');
  const navigate = useNavigate();
  const signedIn = getSession() !== null;
  return (
    <section className="flex flex-col gap-3 px-4 pt-3 pb-6">
      <JobsSegments current="mine" />
      <div className="flex items-center justify-between gap-3">
        <Heading variant="h1">{t('segments.mine')}</Heading>
        <IconButton
          icon="plus"
          label={t('mine.new')}
          onClick={() => void navigate({ to: CREATE_PATHS.what })}
        />
      </div>
      {signedIn ? <MyJobs /> : <Empty group={null} />}
    </section>
  );
}

function MyJobs() {
  const { t } = useTranslation('jobs');
  const jobs = useMyJobs();
  const [group, setGroup] = useState<Group | null>(null);
  // новых откликов по бейджу больше, чем в списке, — список устарел
  const badge = useBadges().data?.jobs;
  const listed = jobs.data?.items.reduce(
    (sum, job) => sum + (job.status === 'published' ? (job.new_responses ?? 0) : 0),
    0,
  );
  const { refetch } = jobs;
  useEffect(() => {
    if (badge !== undefined && listed !== undefined && badge > listed) void refetch();
  }, [badge, listed, refetch]);

  if (jobs.isError) {
    return (
      <LoadError
        error={jobs.error}
        onRetry={() => void jobs.refetch()}
        retrying={jobs.isRefetching}
      />
    );
  }
  if (!jobs.data) {
    // заголовок группы и карточки заявок — на своих местах; чипов у большинства нет
    return (
      <div aria-busy="true" className="flex flex-col gap-3">
        <SkeletonText size="cap" screen className="w-1/4" />
        <JobCardSkeleton />
        <JobCardSkeleton />
      </div>
    );
  }
  const items = [...jobs.data.items].sort(byAttention);
  if (items.length === 0) return <Empty group={null} />;
  const filters = items.length >= FILTERS_FROM;
  const shown = filters && group ? items.filter((job) => GROUP_OF[job.status] === group) : items;
  return (
    <>
      {filters && (
        <Chips label={t('mine.groupsLabel')}>
          {([null, ...GROUPS] as const).map((item) => (
            <Chip key={item ?? 'all'} selected={item === group} onClick={() => setGroup(item)}>
              {t(`mine.groups.${item ?? 'all'}`)}
            </Chip>
          ))}
        </Chips>
      )}
      {shown.length === 0 ? (
        <Empty group={group} />
      ) : filters && group ? (
        shown.map((job) => <MyJobCard key={job.id} job={job} />)
      ) : (
        GROUPS.map((section) => {
          const jobsOf = shown.filter((job) => GROUP_OF[job.status] === section);
          if (jobsOf.length === 0) return null;
          return (
            <section key={section} className="flex flex-col gap-3">
              <SectionTitle as="h2">{t(`mine.groups.${section}`)}</SectionTitle>
              {jobsOf.map((job) => (
                <MyJobCard key={job.id} job={job} />
              ))}
            </section>
          );
        })
      )}
    </>
  );
}

function MyJobCard({ job }: { job: JobOut }) {
  const { t } = useTranslation('jobs');
  const format = useFormat();
  const locale = useLocale();
  const router = useRouter();
  const whenBadge = useWhenBadge();
  const budgetText = useBudgetText();
  const place = useDistrictName(job.city_id, job.district_id);
  const tree = useCategories(locale).data ?? [];
  const category = findCategory(tree, job.category_id)?.name ?? null;
  const budget = budgetText(job);
  const when = whenBadge(job);
  const open = job.status === 'published';
  const active = GROUP_OF[job.status] === 'active';
  const responses = job.responses_count;
  const fresh = job.new_responses ?? 0;
  // итог — словом словаря с датой: у выполненной и закрытой — когда закрыли, у истёкшей — срок;
  // у заявки «В работе» даты нет (раньше ей доставалась «Закрыта» со сроком истечения)
  const ended =
    job.status === 'completed' || job.status === 'closed'
      ? job.closed_at
      : job.status === 'expired'
        ? job.expires_at
        : null;
  const endedKey =
    job.status === 'completed'
      ? 'mine.completedOn'
      : job.status === 'expired'
        ? 'mine.expiredOn'
        : 'mine.closedOn';
  return (
    <Card
      tight
      href={router.history.createHref(managePath(job.id))}
      onClick={(event) => {
        event.preventDefault();
        void router.navigate({ to: managePath(job.id) });
      }}
    >
      <div className="flex items-start justify-between gap-3">
        <h3 className={`m-0 text-title ${active ? '' : 'text-text2'}`}>{job.title}</h3>
        {budget ? (
          <Price className={active ? undefined : 'text-text2'}>{budget}</Price>
        ) : (
          <span className="shrink-0 text-price text-text2">{t('card.negotiable')}</span>
        )}
      </div>
      {active ? (
        <>
          {/* строки как у карточки ленты (JobCard): бейджам — вся ширина, время — справа от
              района, места — своей строкой; ничего не переносится от длины текстов */}
          <div className="flex flex-wrap gap-1.5">
            {open ? (
              <Badge tone={when.tone} icon={when.icon}>
                {when.label}
              </Badge>
            ) : (
              <Badge tone={job.status === 'rejected' ? 'danger' : 'urgent'}>
                {t(`mine.status.${job.status}`)}
              </Badge>
            )}
            {category && <Badge>{category}</Badge>}
          </div>
          <div className="flex items-center justify-between gap-3 text-cap text-text2">
            {place && (
              <span className="flex min-w-0 items-center gap-1.5">
                <Icon name="pin" size={16} className="shrink-0" />
                <span className="truncate">{place}</span>
              </span>
            )}
            {job.published_at && (
              <span className="ml-auto shrink-0">
                {format.relative(new Date(job.published_at))}
              </span>
            )}
          </div>
          {open && responses === 0 ? (
            <Text as="span" variant="cap">
              {t('mine.waiting')}
            </Text>
          ) : (
            <MiniSlots job={job} full />
          )}
          {open && responses > 0 && (
            <Banner tone="ok">
              <span className="flex items-center justify-between gap-2">
                <b>{t('mine.responses', { count: responses })}</b>
                {fresh > 0 && <Badge tone="ok">{t('mine.fresh', { count: fresh })}</Badge>}
              </span>
            </Banner>
          )}
        </>
      ) : (
        <div className="flex flex-wrap items-center justify-between gap-2">
          {/* дата уже говорит статус — бейджем его не повторяем */}
          {!ended && <Badge>{t(`mine.status.${job.status}`)}</Badge>}
          {ended && (
            <Text as="span" variant="cap">
              {t(endedKey, { date: format.dateGenitive(new Date(ended)) })}
            </Text>
          )}
        </div>
      )}
    </Card>
  );
}

function Empty({ group }: { group: Group | null }) {
  const { t } = useTranslation('jobs');
  const navigate = useNavigate();
  return group === null ? (
    <EmptyState
      as="h2"
      icon="jobs"
      title={t('mine.emptyTitle')}
      action={
        <Button variant="secondary" onClick={() => void navigate({ to: CREATE_PATHS.what })}>
          {t('mine.emptyAction')}
        </Button>
      }
    >
      {t('mine.emptyText')}
    </EmptyState>
  ) : (
    <EmptyState as="h2" icon="jobs" title={t('mine.emptyGroup')} />
  );
}
