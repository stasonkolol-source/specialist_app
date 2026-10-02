// Профиль скрыт, снят санкцией или его нет (404 BFF, битая ссылка — 422): без объяснения
// почему — так же, как поиск его не показывает. Ведёт к другим специалистам (S04).
import { useTranslation } from '@sosed/i18n';
import { Button, EmptyState } from '@sosed/ui-web';
import { useRouter } from '@tanstack/react-router';

import { CATALOG_PATHS } from './paths.ts';

export function Unavailable() {
  const { t } = useTranslation('catalog');
  const router = useRouter();
  return (
    <section className="flex flex-col px-4 pt-3 pb-6">
      <EmptyState
        as="h1"
        size="h2"
        tone="neutral"
        icon="user"
        title={t('profile.unavailableTitle')}
        className="px-6 pt-2"
        action={
          <Button
            variant="secondary"
            onClick={() => void router.navigate({ to: CATALOG_PATHS.categories })}
          >
            {t('profile.toCatalog')}
          </Button>
        }
      >
        {t('profile.unavailableText')}
      </EmptyState>
    </section>
  );
}
