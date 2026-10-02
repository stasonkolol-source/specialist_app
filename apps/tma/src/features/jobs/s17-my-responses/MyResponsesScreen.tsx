// S17 Мои отклики: сегмент вкладки «Заявки» (DEVELOPMENT_PLAN 5.3); экран по макету — с откликами
// (5.5).
import { useTranslation } from '@sosed/i18n';
import { EmptyState, Heading } from '@sosed/ui-web';

import { JobsSegments } from '../shared/JobsSegments.tsx';

export function MyResponsesScreen() {
  const { t } = useTranslation('jobs');
  const { t: common } = useTranslation();
  return (
    <section className="flex flex-col gap-3 px-4 pt-3 pb-6">
      <JobsSegments current="responses" />
      <Heading variant="h1">{t('segments.responses')}</Heading>
      <EmptyState as="h2" icon="send" title={common('stub.title')}>
        {common('stub.text')}
      </EmptyState>
    </section>
  );
}
