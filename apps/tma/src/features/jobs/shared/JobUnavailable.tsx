// «Заявка недоступна»: чужая неопубликованная, закрытая или удалённая — S15 и отклик S16.
import { useTranslation } from '@sosed/i18n';
import { Button, EmptyState } from '@sosed/ui-web';

export function JobUnavailable({ onFeed }: { onFeed: () => void }) {
  const { t } = useTranslation('jobs');
  return (
    <section className="px-4 pt-6">
      <EmptyState
        as="h1"
        icon="jobs"
        title={t('job.unavailableTitle')}
        action={
          <Button variant="secondary" onClick={onFeed}>
            {t('job.toFeed')}
          </Button>
        }
      >
        {t('job.unavailableText')}
      </EmptyState>
    </section>
  );
}
