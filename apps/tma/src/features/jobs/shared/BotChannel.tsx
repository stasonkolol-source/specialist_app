// Контекстный запрос «разрешите боту писать» (ADR-0011, ARCHITECTURE §11.1): после публикации
// заявки (S21 — строкой «Разрешите боту писать…» вместо обещания «бот напишет») и при подписке на
// заявки (S18, «Присылать новые заявки в бот?»). Сам канал — хук useBotChannel (@sosed/hooks):
// requestWriteAccess клиента Telegram, затем POST /me/telegram/write-access. Канал уже открыт —
// ничего; разрешили только что — подтверждение.
import { useBotChannel as useChannel } from '@sosed/hooks';
import { usePlatform } from '@sosed/platform';
import { Banner, Button, Card, Heading, Text } from '@sosed/ui-web';

export interface BotChannelTexts {
  title: string;
  text: string;
  allow: string;
  on: string;
  denied: string;
}

/** Канал бота: пишет ли бот (null — настройки ещё не пришли), можно ли спросить разрешение у
 *  клиента Telegram и сам запрос. Экраны результата (S21, S23) по нему выбирают, что обещать. */
export function useBotChannel() {
  return useChannel(usePlatform());
}

export function BotChannel({ texts }: { texts: BotChannelTexts }) {
  const { writable, canAsk, allow } = useBotChannel();
  if (writable === null || !canAsk) return null;
  if (writable) {
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
