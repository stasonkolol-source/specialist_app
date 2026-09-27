// S20a «Что нужно сделать»: каркас маршрута (0.21a). MainButton «Далее» показывает правило
// оболочки: пока видна главная кнопка, таббара нет; «Назад» — нативная кнопка Telegram.
import { useTranslation } from '@sosed/i18n';
import { useBackButton, useMainButton } from '@sosed/platform';
import { EmptyState, Heading } from '@sosed/ui-web';
import { useRouter } from '@tanstack/react-router';

export function CreateJobScreen() {
  const { t } = useTranslation();
  const router = useRouter();
  useBackButton(() => router.history.back());
  useMainButton({ text: t('action.next'), enabled: false, onClick: () => undefined });
  return (
    <section className="flex flex-col gap-2 px-4 pt-4">
      <Heading variant="h1">{t('nav.create')}</Heading>
      <EmptyState icon="plus" title={t('stub.title')}>
        {t('stub.text')}
      </EmptyState>
    </section>
  );
}
