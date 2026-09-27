// S29 Сообщения: каркас маршрута (0.21a); экран по макету design/project — в шаге этапа 1.
import { useTranslation } from '@sosed/i18n';
import { EmptyState, Heading } from '@sosed/ui-web';

export function ChatsScreen() {
  const { t } = useTranslation();
  return (
    <section className="flex flex-col gap-2 px-4 pt-4">
      <Heading variant="h1">{t('nav.messages')}</Heading>
      <EmptyState as="h2" icon="chat" title={t('stub.title')}>
        {t('stub.text')}
      </EmptyState>
    </section>
  );
}
