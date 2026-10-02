// S43 Настройки (DEVELOPMENT_PLAN 6.5, 4.9): пока — раздел «Показывать после договорённости»:
// «Мой Telegram» (по умолчанию включён) — ссылка на свой Telegram второй стороне в сделке и в чате.
// Телефоном делятся в чате кнопкой «Поделиться контактом» (S54); переключатель «Мой номер
// телефона» — с подтверждением номера (v1). Язык, город, уведомления и тихие часы — шаг 4.9.
import { useIdentityGetMe } from '@sosed/api-client';
import { useUpdatePrivacy } from '@sosed/hooks';
import { useTranslation } from '@sosed/i18n';
import { useBackButton } from '@sosed/platform';
import { Banner, Group, Heading, SectionTitle, Switch, Text } from '@sosed/ui-web';
import { useRouter } from '@tanstack/react-router';
import { useId } from 'react';

import { ACCOUNT_PATHS } from '../paths.ts';

export function SettingsScreen() {
  const { t } = useTranslation('service');
  const router = useRouter();
  useBackButton(() => {
    if (router.history.canGoBack()) router.history.back();
    else void router.navigate({ to: ACCOUNT_PATHS.home, replace: true });
  });
  const me = useIdentityGetMe();
  const update = useUpdatePrivacy();
  const privacyId = useId();
  const telegramId = useId();
  const showTelegram = update.isPending
    ? (update.variables.show_telegram ?? true)
    : (me.data?.privacy.show_telegram ?? true);

  return (
    <section className="flex flex-col gap-3 px-4 pt-3 pb-6">
      <Heading variant="h1">{t('settings.title')}</Heading>
      <section aria-labelledby={privacyId} className="flex flex-col gap-2">
        <SectionTitle as="h2" id={privacyId}>
          {t('settings.privacyTitle')}
        </SectionTitle>
        <Group>
          <div className="flex items-center gap-3 px-4 py-3">
            <span className="flex flex-1 flex-col gap-0.5">
              <span id={telegramId}>{t('settings.privacyTelegram')}</span>
              <Text as="span" variant="cap" secondary>
                {t('settings.privacyTelegramHint')}
              </Text>
            </span>
            <Switch
              checked={showTelegram}
              label={t('settings.privacyTelegram')}
              disabled={me.data === undefined || update.isPending}
              onChange={(checked) => update.mutate({ show_telegram: checked })}
            />
          </div>
        </Group>
        <Text variant="cap" secondary className="px-1">
          {t('settings.privacyPhoneHint')}
        </Text>
        {update.isError && (
          <Banner tone="danger" role="alert">
            {t('settings.saveError')}
          </Banner>
        )}
      </section>
    </section>
  );
}
