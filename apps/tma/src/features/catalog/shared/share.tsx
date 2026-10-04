// «Поделиться» карточки специалиста (DEVELOPMENT_PLAN 7.4): S08 и S10. Логика — useShare
// (@sosed/hooks): карточка в выбор чата Telegram или ссылка; здесь — тост «Ссылка скопирована» и
// сообщение об ошибке над таббаром.
import { useShare } from '@sosed/hooks';
import { useTranslation } from '@sosed/i18n';
import { usePlatform } from '@sosed/platform';
import { Toast } from '@sosed/ui-web';

export function useProfileShare(profileId: string) {
  const { t } = useTranslation();
  const platform = usePlatform();
  const { share, pending, failed, copied } = useShare(platform);
  let notice = null;
  if (copied) notice = <Toast icon="link">{t('share.copied')}</Toast>;
  else if (failed) notice = <Toast icon="alert">{t('share.failed')}</Toast>;
  return {
    share: () => share({ type: 'specialist', id: profileId }),
    pending,
    notice,
  };
}
