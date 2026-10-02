// S22 Мои заявки (DEVELOPMENT_PLAN 5.6): сегмент вкладки «Заявки». Чипы «Все / Активные / В
// работе / Завершённые / Архив» (на «Все» — разделами), «+» — новая заявка S20a. Карточка — название
// и бюджет, «когда» и категория, район и места «откликов 3 из 5» или «Ждём откликов»; есть отклики
// — «3 отклика — выберите исполнителя» и «2 новых», пока клиент их не открыл; на проверке, нужно
// исправить, закрыта — словами. Нажатие — своя заявка S23.
import type { JobOut, JobStatus } from '@sosed/api-client';
import { getSession } from '@sosed/api-client';
import { useCategories, useMyJobs } from '@sosed/hooks';
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
  IconButton,
  Price,
  SectionTitle,
  Skeleton,
  Text,
} from '@sosed/ui-web';
import { useNavigate, useRouter } from '@tanstack/react-router';
import { useState } from 'react';

import { JobsSegments } from '../shared/JobsSegments.tsx';
import { LoadError } from '../shared/LoadError.tsx';
import { MiniSlots } from '../shared/MiniSlots.tsx';
import { findCategory } from '../shared/categories.ts';
import { useBudgetText, useDistrictName, useWhenBadge } from '../shared/labels.ts';
import { CREATE_PATHS, managePath } from '../shared/paths.ts';

type Group = 'active' | 'work' | 'done' | 'archive';
const GROUPS: readonly Group[] = ['active', 'work', 'done', 'archive'];
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
    return (
      <>
        <Skeleton radius="card" className="h-36 w-full" />
        <Skeleton radius="card" className="h-36 w-full" />
      </>
    );
  }
  const items = jobs.data.items;
  if (items.length === 0) return <Empty group={null} />;
  const shown = group ? items.filter((job) => GROUP_OF[job.status] === group) : items;
  return (
    <>
      <Chips label={t('mine.groupsLabel')}>
        {([null, ...GROUPS] as const).map((item) => (
          <Chip key={item ?? 'all'} selected={item === group} onClick={() => setGroup(item)}>
            {t(`mine.groups.${item ?? 'all'}`)}
          </Chip>
        ))}
      </Chips>
      {shown.length === 0 ? (
        <Empty group={group} />
      ) : group ? (
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
  const ended = job.closed_at ?? job.expires_at;
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
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="flex flex-wrap gap-1.5">
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
            </span>
            {job.published_at && (
              <Text as="span" variant="cap">
                {format.relative(new Date(job.published_at))}
              </Text>
            )}
          </div>
          <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1.5">
            <Text as="span" variant="cap">
              {place}
            </Text>
            {open && responses === 0 ? (
              <Text as="span" variant="cap">
                {t('mine.waiting')}
              </Text>
            ) : (
              <MiniSlots job={job} full />
            )}
          </div>
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
          <Badge>{t(`mine.status.${job.status}`)}</Badge>
          {ended && (
            <Text as="span" variant="cap">
              {t(job.status === 'expired' ? 'mine.expiredOn' : 'mine.closedOn', {
                date: format.date(new Date(ended)),
              })}
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
