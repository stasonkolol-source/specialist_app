// Настройки уведомлений S43 (DEVELOPMENT_PLAN 4.9, API 2.3a): группы × каналы и тихие часы.
// PUT заменяет настройки целиком, поэтому каждое нажатие отправляет всё, что видно на экране.
// Нажатие видно сразу (оптимистично). Запросы идут по одному (общий scope): каждый несёт и
// предыдущие отметки, а ответ сервера ложится в кэш, только когда ждать больше нечего, — иначе
// ранний ответ на миг вернул бы отметку, которую человек уже поменял. Ошибка возвращает только
// свою отметку, настройки перечитываются в фоне.
import type {
  EventGroup,
  NotificationSettingsIn,
  NotificationSettingsOut,
} from '@sosed/api-client';
import {
  getNotificationsGetNotificationSettingsQueryKey,
  notificationsUpdateNotificationSettings,
} from '@sosed/api-client';
import { useMutation, useQueryClient } from '@tanstack/react-query';

export type NotificationChannel = 'telegram' | 'in_app';

/** Одно нажатие: отметка «группа × канал» на S43, группа целиком (без `channel`: «Сообщить о
 *  запуске» на S58 и переключатель `goods_launch` на S43, 7.5) или переключатель тихих часов. */
export type SettingsChange =
  { group: EventGroup; channel?: NotificationChannel; on: boolean } | { quiet: boolean };

const KEY = ['notificationSettings', 'update'] as const;

/** Настройки после нажатия — то, что экран покажет до ответа сервера. */
export function applyChange(
  settings: NotificationSettingsOut,
  change: SettingsChange,
): NotificationSettingsOut {
  if ('quiet' in change) {
    return { ...settings, quiet_hours: { ...settings.quiet_hours, enabled: change.quiet } };
  }
  const { group, channel, on } = change;
  return {
    ...settings,
    groups: settings.groups.map((row) => {
      if (row.group !== group || row.mandatory) return row;
      return channel ? { ...row, [channel]: on } : { ...row, telegram: on, in_app: on };
    }),
  };
}

/** Нажатие наоборот — откат одной отметки, если сервер её не сохранил. */
function undo(change: SettingsChange): SettingsChange {
  return 'quiet' in change ? { quiet: !change.quiet } : { ...change, on: !change.on };
}

/** Тело PUT: всё, что видно, кроме служебной группы (её не выключить, сервер её не ждёт). */
export function settingsIn(settings: NotificationSettingsOut): NotificationSettingsIn {
  const { enabled, start, end } = settings.quiet_hours;
  return {
    groups: settings.groups
      .filter((row) => !row.mandatory)
      .map(({ group, telegram, in_app }) => ({ group, telegram, in_app })),
    quiet_hours: { enabled, start, end },
    digest_hour: settings.digest_hour,
  };
}

export function useUpdateNotificationSettings() {
  const client = useQueryClient();
  const key = getNotificationsGetNotificationSettingsQueryKey();
  const patch = (change: SettingsChange) =>
    client.setQueryData<NotificationSettingsOut>(key, (old) => old && applyChange(old, change));
  return useMutation({
    mutationKey: KEY,
    scope: { id: KEY.join(':') },
    onMutate: async (change: SettingsChange) => {
      await client.cancelQueries({ queryKey: key });
      patch(change);
    },
    // тело — из кэша в момент отправки: в нём уже все нажатия, сделанные до этого запроса
    mutationFn: () => {
      const current = client.getQueryData<NotificationSettingsOut>(key);
      if (!current) throw new Error('notification settings are not loaded');
      return notificationsUpdateNotificationSettings(settingsIn(current));
    },
    onSuccess: (saved) => {
      // этот запрос — последний в очереди: ответ сервера и есть то, что на экране
      if (client.isMutating({ mutationKey: KEY }) <= 1) client.setQueryData(key, saved);
    },
    onError: (_error, change) => {
      patch(undo(change));
      void client.invalidateQueries({ queryKey: key });
    },
  });
}
