// Контекстный запрос «разрешите боту писать» (ADR-0011, ARCHITECTURE §11.1): после публикации
// заявки (S21, «Сообщать об откликах?») и при подписке на заявки (S18, «Присылать новые заявки в
// бот?»). requestWriteAccess клиента Telegram, затем POST /me/telegram/write-access; ответ ложится
// в настройки уведомлений. Канал уже открыт — ничего; разрешили только что — подтверждение.
import {
  getNotificationsGetNotificationSettingsQueryKey,
  notificationsGrantTelegramWriteAccess,
  useNotificationsGetNotificationSettings,
} from '@sosed/api-client';
import { usePlatform } from '@sosed/platform';
import { Banner, Button, Card, Heading, Text } from '@sosed/ui-web';
import { useMutation, useQueryClient } from '@tanstack/react-query';

export interface BotChannelTexts {
  title: string;
  text: string;
  allow: string;
  on: string;
  denied: string;
}

export function BotChannel({ texts }: { texts: BotChannelTexts }) {
  const platform = usePlatform();
  const queryClient = useQueryClient();
  const settings = useNotificationsGetNotificationSettings();
  const allow = useMutation({
    mutationFn: async () => {
      if (!(await platform.requestWriteAccess().catch(() => false))) throw new Error('declined');
      return notificationsGrantTelegramWriteAccess();
    },
    onSuccess: (telegram) => {
      queryClient.setQueryData(
        getNotificationsGetNotificationSettingsQueryKey(),
        (current: typeof settings.data) => current && { ...current, telegram },
      );
    },
  });
  const channel = settings.data?.telegram;
  if (!settings.data || !platform.capabilities.requestWriteAccess) return null;
  if (channel?.writable) {
    // разрешили только что — подтверждаем; было разрешено раньше — нечего показывать
    return allow.isSuccess ? (
      <Banner tone="ok" icon="bell" role="status">
        {texts.on}
      </Banner>
    ) : null;
  }
  return (
    <Card className="flex flex-col gap-2">
      <Heading variant="h3" as="h2">
        {texts.title}
      </Heading>
      <Text secondary>{texts.text}</Text>
      <Button
        variant="secondary"
        icon="bell"
        onClick={() => allow.mutate()}
        disabled={allow.isPending}
        aria-busy={allow.isPending}
      >
        {texts.allow}
      </Button>
      {allow.isError && (
        <Text variant="cap" className="text-danger">
          {texts.denied}
        </Text>
      )}
    </Card>
  );
}
