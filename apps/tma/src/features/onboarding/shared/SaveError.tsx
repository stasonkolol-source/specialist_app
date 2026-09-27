// Ошибка сохранения шага: нет сети (S49a — «проверьте интернет») или прочее. Выбор на экране
// остаётся, повтор — той же MainButton.
import { systemStateOf } from '@sosed/hooks';
import { useTranslation } from '@sosed/i18n';
import { Banner } from '@sosed/ui-web';

export function SaveError({ error, message }: { error: unknown; message?: string }) {
  const { t } = useTranslation('onboarding');
  const offline = systemStateOf(error).kind === 'offline';
  return (
    <Banner tone="danger" role="alert" icon={offline ? 'wifi-off' : 'alert'}>
      {offline ? t('offlineError') : (message ?? t('saveError'))}
    </Banner>
  );
}
