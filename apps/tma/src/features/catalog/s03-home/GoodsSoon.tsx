// S58 «Вещи — скоро» (DEVELOPMENT_PLAN 7.5, ADR-0019): сегмент «Вещи» Главной до запуска раздела.
// Модуля goods нет — только сигнал спроса: «Сообщить о запуске» включает группу уведомлений
// `goods_launch` (PUT /me/notification-settings), сервер пишет событие `goods_waitlist_joined`.
// Кнопка — в контенте, не MainButton: таббар на экране виден. Если боту ещё нельзя писать —
// сначала requestWriteAccess; отказ не мешает подписке: о запуске скажет центр уведомлений S42,
// и «Готово!» говорит именно это. Отписка — переключатель на S43. «Переезжаете?» — обычный мастер
// заявки S20a; ссылки на шаблон «Уезжаю» нет, пока его не примут (Q23). Своим чанком: до выбора
// сегмента экран не нужен (бюджет первого экрана 200 KB gzip).
import type { NotificationSettingsOut } from '@sosed/api-client';
import {
  getNotificationsGetNotificationSettingsQueryKey,
  getSession,
  notificationsGrantTelegramWriteAccess,
  useNotificationsGetNotificationSettings,
} from '@sosed/api-client';
import { useUpdateNotificationSettings } from '@sosed/hooks';
import { useTranslation } from '@sosed/i18n';
import { usePlatform } from '@sosed/platform';
import type { IconName } from '@sosed/ui-web';
import { Banner, Button, Card, Heading, Icon, RowIcon, Text } from '@sosed/ui-web';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useRouter } from '@tanstack/react-router';
import { useId } from 'react';

import { CREATE_JOB_PATH } from '../shared/paths.ts';
import { GoodsIntro } from './GoodsIntro.tsx';

/** «Что здесь будет» — как на артборде S58. */
const FEATURES = [
  ['camera', 'whatPost'],
  ['search', 'whatSearch'],
  ['gift', 'whatFree'],
  ['share', 'whatShare'],
] as const satisfies readonly (readonly [IconName, string])[];

export function GoodsSoon() {
  const { t } = useTranslation('catalog');
  const router = useRouter();
  const featuresId = useId();
  // гостю (браузер без входа) подписываться некуда: остальной экран тот же
  const signedIn = getSession() !== null;
  return (
    <>
      <GoodsIntro />
      <Card as="section" aria-labelledby={featuresId}>
        <Heading variant="h3" as="h2" id={featuresId}>
          {t('goods.whatTitle')}
        </Heading>
        <ul className="m-0 flex list-none flex-col gap-3 p-0">
          {FEATURES.map(([icon, key]) => (
            <li key={key} className="flex items-center gap-3">
              <RowIcon icon={icon} />
              <Text as="span" variant="sm" className="min-w-0 grow">
                {t(`goods.${key}`)}
              </Text>
            </li>
          ))}
        </ul>
      </Card>
      {signedIn && <LaunchOptIn />}
      <Card
        href={router.history.createHref(router.buildLocation({ to: CREATE_JOB_PATH }).href)}
        onClick={(event) => {
          event.preventDefault();
          void router.navigate({ to: CREATE_JOB_PATH });
        }}
      >
        <span className="flex items-center gap-3">
          <RowIcon icon="truck" palette={3} xl />
          <span className="flex min-w-0 grow flex-col gap-1">
            <span className="font-semibold">{t('goods.movingTitle')}</span>
            <Text as="span" variant="cap">
              {t('goods.movingText')}
            </Text>
          </span>
          <Icon name="chev-right" className="shrink-0 text-text2" />
        </span>
      </Card>
    </>
  );
}

/** «Сообщить о запуске» → «Готово!»: подписка — группа `goods_launch` в обоих каналах. */
function LaunchOptIn() {
  const { t } = useTranslation('catalog');
  const platform = usePlatform();
  const queryClient = useQueryClient();
  const settings = useNotificationsGetNotificationSettings();
  const update = useUpdateNotificationSettings();
  const subscribe = useMutation({
    mutationFn: async () => {
      const telegram = settings.data?.telegram;
      if (!telegram?.writable && platform.capabilities.requestWriteAccess) {
        const allowed = await platform.requestWriteAccess().catch(() => false);
        // разрешение не записалось (сеть) — подписка всё равно нужна: скажем в приложении
        const granted = allowed
          ? await notificationsGrantTelegramWriteAccess().catch(() => null)
          : null;
        if (granted) {
          queryClient.setQueryData<NotificationSettingsOut>(
            getNotificationsGetNotificationSettingsQueryKey(),
            (current) => current && { ...current, telegram: granted },
          );
        }
      }
      await update.mutateAsync({ group: 'goods_launch', on: true });
    },
  });
  const row = settings.data?.groups.find((group) => group.group === 'goods_launch');
  if (row && (row.telegram || row.in_app)) {
    // бот не может писать — о запуске скажет центр уведомлений: так и обещаем
    const bot = row.telegram && settings.data?.telegram?.writable === true;
    return (
      <Banner tone="ok" role="status">
        {t(bot ? 'goods.done' : 'goods.doneInApp')}
      </Banner>
    );
  }
  const busy = subscribe.isPending || settings.isPending;
  return (
    <div className="flex flex-col gap-2">
      <Button
        full
        icon="bell"
        className="h-12.5"
        onClick={() => subscribe.mutate()}
        disabled={busy}
        aria-busy={busy}
      >
        {t('goods.notify')}
      </Button>
      {subscribe.isError ? (
        <p role="alert" className="m-0 text-center text-cap text-danger">
          {t('goods.error')}
        </p>
      ) : (
        <Text variant="cap" secondary className="text-center">
          {t('goods.notifyHint')}
        </Text>
      )}
    </div>
  );
}
