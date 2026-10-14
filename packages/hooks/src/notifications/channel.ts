// Канал бота «пишет в личный чат» (ADR-0011, ARCHITECTURE §11.1): может ли бот писать и
// контекстный запрос разрешения — requestWriteAccess клиента Telegram, затем
// POST /me/telegram/write-access; ответ ложится в настройки уведомлений, и экраны, которые
// обещают «бот напишет», видят его сразу. Клиент Telegram хук получает снаружи (packages/platform)
// и знает о нём только нужное: хуки — без Telegram, их переиспользует мобильное приложение.
import type { NotificationSettingsOut } from '@sosed/api-client';
import {
  getNotificationsGetNotificationSettingsQueryKey,
  notificationsGrantTelegramWriteAccess,
  useNotificationsGetNotificationSettings,
} from '@sosed/api-client';
import { useMutation, useQueryClient } from '@tanstack/react-query';

/** Что хуку нужно от клиента Telegram: умеет ли он спросить разрешение и сам вопрос. */
export interface WriteAccessClient {
  capabilities: { requestWriteAccess: boolean };
  /** true — разрешил; false — отказался. Клиент уже дал разрешение — отвечает true без попапа. */
  requestWriteAccess(): Promise<boolean>;
}

/** Человек не разрешил боту писать (или клиент не ответил): на сервер ничего не уходит. */
export class WriteAccessDeclinedError extends Error {
  constructor() {
    super('write access declined');
    this.name = 'WriteAccessDeclinedError';
  }
}

export type BotChannel = ReturnType<typeof useBotChannel>;

/** Канал бота: пишет ли бот (`null` — настройки ещё не пришли или не запрошены), можно ли спросить
 *  разрешение у клиента и сам запрос `allow`. `enabled: false` — настройки не запрашивать, пока
 *  экрану нечего обещать. */
export function useBotChannel(client: WriteAccessClient, { enabled = true } = {}) {
  const queryClient = useQueryClient();
  const settings = useNotificationsGetNotificationSettings({ query: { enabled } });
  const allow = useMutation({
    mutationFn: async () => {
      const allowed = await client.requestWriteAccess().catch(() => false);
      if (!allowed) throw new WriteAccessDeclinedError();
      return notificationsGrantTelegramWriteAccess();
    },
    onSuccess: async (telegram) => {
      const key = getNotificationsGetNotificationSettingsQueryKey();
      // GET, ушедший до разрешения (экран только открылся), ответил бы «канала нет» и затёр его
      await queryClient.cancelQueries({ queryKey: key });
      queryClient.setQueryData<NotificationSettingsOut>(
        key,
        (current) => current && { ...current, telegram },
      );
      // настроек в кэше ещё не было — перечитать: сервер уже знает о канале
      if (!queryClient.getQueryData(key)) void queryClient.invalidateQueries({ queryKey: key });
    },
  });
  return {
    writable: settings.data ? Boolean(settings.data.telegram?.writable) : null,
    canAsk: client.capabilities.requestWriteAccess,
    allow,
  };
}
