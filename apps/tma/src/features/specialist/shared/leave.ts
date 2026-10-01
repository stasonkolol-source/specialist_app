// Уход с экрана, пока файлы грузятся (S37, S34): незаконченные загрузки экрана остановятся —
// сначала спросить. Закрыть Mini App в это время Telegram тоже не даст без подтверждения.
import { useTranslation } from '@sosed/i18n';
import { useClosingConfirmation, usePlatform } from '@sosed/platform';
import { useBlocker } from '@tanstack/react-router';

export function useUploadGuard(busy: boolean) {
  const { t } = useTranslation('specialist');
  const platform = usePlatform();
  useClosingConfirmation(busy);
  useBlocker({
    disabled: !busy,
    enableBeforeUnload: false,
    shouldBlockFn: async () => !(await platform.confirm(t('uploads.leave'))),
  });
}
