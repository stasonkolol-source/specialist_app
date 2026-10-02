// Плашка прямого запроса в мастере S20a и S20d (DEVELOPMENT_PLAN 5.6): заявку увидит только
// выбранный специалист; «Отправить всем исполнителям» делает её обычной.
import type { DirectTarget } from '@sosed/hooks';
import { useTranslation } from '@sosed/i18n';
import { Banner, LinkButton } from '@sosed/ui-web';

export function DirectBanner({ direct, onAll }: { direct: DirectTarget; onAll: () => void }) {
  const { t } = useTranslation('jobs');
  return (
    <Banner tone="info" icon="send">
      <span className="flex flex-col items-start gap-1">
        <span>{t('create.direct.banner', { name: direct.name })}</span>
        <LinkButton onClick={onAll} className="-ml-2">
          {t('create.direct.all')}
        </LinkButton>
      </span>
    </Banner>
  );
}
