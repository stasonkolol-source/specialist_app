// Ошибка сохранения шага: нет сети (S49a — «проверьте интернет»), отказ сервера с пояснением
// (`detail` приходит на языке интерфейса: «категория недоступна», «слишком длинно») или прочее.
// Ввод на экране остаётся, повтор — той же MainButton.
import { ApiError } from '@sosed/api-client';
import { systemStateOf } from '@sosed/hooks';
import { useTranslation } from '@sosed/i18n';
import { Banner } from '@sosed/ui-web';

export function SaveError({ error }: { error: unknown }) {
  const { t } = useTranslation('specialist');
  const offline = systemStateOf(error).kind === 'offline';
  const detail = error instanceof ApiError && error.status < 500 ? error.problem.detail : null;
  return (
    <Banner tone="danger" role="alert" icon={offline ? 'wifi-off' : 'alert'}>
      {offline ? t('become.offlineError') : (detail ?? t('become.saveError'))}
    </Banner>
  );
}
