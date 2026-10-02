// S22 Мои заявки: сегмент вкладки «Заявки» (DEVELOPMENT_PLAN 5.3); экран по макету — в шаге 5.6.
import { useTranslation } from '@sosed/i18n';
import { EmptyState, Heading } from '@sosed/ui-web';

import { JobsSegments } from '../shared/JobsSegments.tsx';

export function MyJobsScreen() {
  const { t } = useTranslation('jobs');
  const { t: common } = useTranslation();
  return (
    <section className="flex flex-col gap-3 px-4 pt-3 pb-6">
      <JobsSegments current="mine" />
      <Heading variant="h1">{t('segments.mine')}</Heading>
      <EmptyState as="h2" icon="jobs" title={common('stub.title')}>
        {common('stub.text')}
      </EmptyState>
    </section>
  );
}
