// «Мои активные заявки» на S03 (DEVELOPMENT_PLAN 5.6): у клиента есть открытые заявки — до трёх
// строк с откликами («3 отклика · 2 новых», «Ждём откликов», «На проверке»), нажатие — своя заявка
// S23. Нет активных — блока нет. Своим чанком: список заявок до первого кадра Главной не нужен.
// Пока список не пришёл — `pending` (скелетон у клиента: блок над разделами не сдвигает их вниз).
import type { JobOut } from '@sosed/api-client';
import { useMyJobs } from '@sosed/hooks';
import { useTranslation } from '@sosed/i18n';
import { Group, Heading, Row, RowIcon } from '@sosed/ui-web';
import { useRouter } from '@tanstack/react-router';
import type { ReactNode } from 'react';
import { useId } from 'react';

import { managedJobPath } from '../shared/paths.ts';

const SHOWN = 3;
const ACTIVE: ReadonlySet<JobOut['status']> = new Set(['published', 'pending_moderation']);

export function MyActiveJobs({ pending = null }: { pending?: ReactNode }) {
  const { t } = useTranslation('catalog');
  const router = useRouter();
  const titleId = useId();
  const query = useMyJobs();
  const jobs = (query.data?.items ?? []).filter((job) => ACTIVE.has(job.status));
  if (query.isPending) return pending;
  if (jobs.length === 0) return null;
  const subtitle = (job: JobOut) => {
    if (job.status !== 'published') return t('home.myJobsReview');
    if (job.responses_count === 0) return t('home.myJobsWaiting');
    const fresh = job.new_responses ?? 0;
    const responses = t('home.myJobsResponses', { count: job.responses_count });
    return fresh > 0 ? `${responses} · ${t('home.myJobsFresh', { count: fresh })}` : responses;
  };
  return (
    <section aria-labelledby={titleId} className="flex flex-col gap-3">
      <Heading variant="h3" as="h2" id={titleId}>
        {t('home.myJobs')}
      </Heading>
      <Group>
        {jobs.slice(0, SHOWN).map((job) => (
          <Row
            key={job.id}
            leading={<RowIcon icon="jobs" palette={2} />}
            title={job.title}
            subtitle={subtitle(job)}
            chevron
            href={router.history.createHref(managedJobPath(job.id))}
            onClick={(event) => {
              event.preventDefault();
              void router.navigate({ to: managedJobPath(job.id) });
            }}
          />
        ))}
      </Group>
    </section>
  );
}
