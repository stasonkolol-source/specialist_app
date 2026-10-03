// S43 Настройки (DEVELOPMENT_PLAN 4.9; раздел приватности — 6.5). Вход — строки «Язык» и
// «Настройки» на S31, шестерёнка S42 и кнопка «Все настройки» бота (/settings, `m_settings`).
// Сверху вниз, как на артборде: язык интерфейса (он же язык бота), город, уведомления «группа ×
// канал» и тихие часы, «Показывать после договорённости», экспорт данных и удаление аккаунта,
// версия приложения.
// «Мой Telegram» (по умолчанию включён) — ссылка на свой Telegram второй стороне в сделке и в чате.
// Телефоном делятся в чате кнопкой «Поделиться контактом» (S54); переключатель «Мой номер
// телефона» — с подтверждением номера (v1).
// «Экспорт моих данных» — запрос в поддержку (runbook 2.12, выгрузку делает `cli export-user-data`):
// строка открывает чат с аккаунтом поддержки из client-config; пока его нет (K23, Q25) — «скоро».
// «Заблокированные» (S44, 4.7) — сколько человек заблокировано: список тот же, что у S44.
import type { MeOut } from '@sosed/api-client';
import { useIdentityGetMe } from '@sosed/api-client';
import { useBlocks, useSupportLink, useUpdatePrivacy } from '@sosed/hooks';
import { useTranslation } from '@sosed/i18n';
import { useBackButton, usePlatform } from '@sosed/platform';
import {
  Badge,
  Banner,
  Group,
  Heading,
  Row,
  SectionTitle,
  Skeleton,
  SkeletonText,
  Switch,
  Text,
} from '@sosed/ui-web';
import { useRouter } from '@tanstack/react-router';
import type { MouseEvent } from 'react';
import { useId } from 'react';

import { ACCOUNT_PATHS } from '../paths.ts';
import { City } from './City.tsx';
import { Language } from './Language.tsx';
import { Notifications } from './Notifications.tsx';

export function SettingsScreen() {
  const { t } = useTranslation('account');
  const router = useRouter();
  useBackButton(() => {
    if (router.history.canGoBack()) router.history.back();
    else void router.navigate({ to: ACCOUNT_PATHS.home, replace: true });
  });
  const me = useIdentityGetMe();

  return (
    <section className="flex flex-col gap-2.5 px-4 pt-3 pb-6">
      <Heading variant="h2" as="h1">
        {t('settings.title')}
      </Heading>
      {me.data ? (
        <>
          <Language me={me.data} />
          <City me={me.data} />
        </>
      ) : (
        <ProfileLoading />
      )}
      <Notifications />
      <Privacy me={me.data} />
      <AccountActions />
      <Text variant="cap" className="pt-1 text-center">
        {t('settings.version', { version: __APP_VERSION__ })}
      </Text>
    </section>
  );
}

/** Язык и город ждут /me: фигуры сегментов и строки города на своих местах. */
function ProfileLoading() {
  const { t } = useTranslation('account');
  return (
    <div role="status" className="flex flex-col gap-2.5">
      <span className="sr-only">{t('settings.loading')}</span>
      <div aria-hidden="true" className="flex flex-col gap-2">
        <SkeletonText size="cap" screen className="mx-4 w-32" />
        <Skeleton screen radius="panel" className="h-11.5" />
        <SkeletonText size="cap" screen className="mx-4 w-28" />
      </div>
      <Group>
        <div aria-hidden="true" className="flex min-h-13 items-center gap-3 px-4 py-3">
          <Skeleton radius="icon" className="size-9 shrink-0" />
          <SkeletonText className="w-1/3" />
        </div>
      </Group>
    </div>
  );
}

/** «Показывать после договорённости» (6.5): «Мой Telegram»; телефон — кнопкой в чате (S54). */
function Privacy({ me }: { me: MeOut | undefined }) {
  const { t } = useTranslation('account');
  const update = useUpdatePrivacy();
  const titleId = useId();
  const telegramId = useId();
  const showTelegram = update.isPending
    ? (update.variables.show_telegram ?? true)
    : (me?.privacy.show_telegram ?? true);
  return (
    <section aria-labelledby={titleId} className="flex flex-col gap-2">
      <SectionTitle id={titleId}>{t('settings.privacyTitle')}</SectionTitle>
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
            disabled={me === undefined || update.isPending}
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
  );
}

/** Заблокированные S44 (с числом), экспорт данных — через поддержку; удаление — S45 с
 *  последствиями и подтверждением. */
function AccountActions() {
  const { t } = useTranslation('account');
  const router = useRouter();
  const platform = usePlatform();
  const support = useSupportLink();
  const blocks = useBlocks();
  const open = (to: string) => (event: MouseEvent<HTMLElement>) => {
    event.preventDefault();
    void router.navigate({ to });
  };
  const blockedCount = blocks.data?.items.length;
  return (
    <Group>
      <Row
        icon="ban"
        title={t('settings.blocked')}
        trailing={
          blockedCount ? (
            <Text as="span" variant="sm" secondary>
              {blockedCount}
            </Text>
          ) : undefined
        }
        chevron
        href={router.history.createHref(ACCOUNT_PATHS.blocked)}
        onClick={open(ACCOUNT_PATHS.blocked)}
      />
      {support ? (
        <Row
          icon="file"
          title={t('settings.export')}
          subtitle={t('settings.exportHint')}
          chevron
          onClick={() => platform.openTelegramLink(support)}
        />
      ) : (
        <Row
          icon="file"
          title={t('settings.export')}
          subtitle={t('settings.exportHint')}
          trailing={<Badge tone="mute">{t('settings.soon')}</Badge>}
        />
      )}
      <Row
        icon="trash"
        title={t('deletion.row')}
        danger
        chevron
        href={router.history.createHref(ACCOUNT_PATHS.delete)}
        onClick={open(ACCOUNT_PATHS.delete)}
      />
    </Group>
  );
}
