// S54 «Поделиться контактом» (DEVELOPMENT_PLAN 6.5; ADR-0010): после договорённости сторона сама
// отмечает, что отправить, — галочками, как на артборде: имя пользователя Telegram (если оно есть
// и «Мой Telegram» включён в настройках) и/или телефон (Telegram спросит подтверждение и отдаст
// подписанный номер). Каждый контакт уходит собеседнику отдельным сообщением в чате. Памятка:
// никому не сообщать коды из SMS и данные карты.
import type { ContactShareIn, MeOut } from '@sosed/api-client';
import { ApiError, getIdentityGetMeQueryKey } from '@sosed/api-client';
import { useShareContact } from '@sosed/hooks';
import { useTranslation } from '@sosed/i18n';
import { usePlatform } from '@sosed/platform';
import { Banner, Button, Option, Sheet, Stack, Text } from '@sosed/ui-web';
import { useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

type Choice = 'telegram' | 'phone';

/** Имя пользователя из initData клиента — только для подписи: backend проверит его подпись. */
export function launchUsername(rawInitData: string | null): string | null {
  if (!rawInitData) return null;
  try {
    const user: unknown = JSON.parse(new URLSearchParams(rawInitData).get('user') ?? 'null');
    const username = user && typeof user === 'object' && 'username' in user ? user.username : null;
    return typeof username === 'string' && username !== '' ? username : null;
  } catch {
    return null;
  }
}

export function ShareContactSheet({
  open,
  conversationId,
  onClose,
}: {
  open: boolean;
  conversationId: string;
  onClose: () => void;
}) {
  const { t } = useTranslation('messages');
  const { t: common } = useTranslation();
  const platform = usePlatform();
  const queryClient = useQueryClient();
  const share = useShareContact(conversationId);
  const [notSent, setNotSent] = useState(false);
  const me = queryClient.getQueryData<MeOut>(getIdentityGetMeQueryKey());
  const username = launchUsername(platform.launch.rawInitData);
  const choices: Choice[] = [];
  if (username && me?.privacy.show_telegram !== false) choices.push('telegram');
  if (platform.capabilities.requestContact) choices.push('phone');
  // по умолчанию отмечен первый вариант, как на артборде; дальше — что отметил человек
  const [picked, setPicked] = useState<ReadonlySet<Choice> | null>(null);
  const checked = picked ?? new Set(choices.slice(0, 1));
  const selected = choices.filter((value) => checked.has(value));
  const busy = share.isPending;
  const toggle = (value: Choice, on: boolean) => {
    const next = new Set(checked);
    if (on) next.add(value);
    else next.delete(value);
    setPicked(next);
  };

  const send = async () => {
    setNotSent(false);
    const contacts: [Choice, ContactShareIn][] = [];
    if (selected.includes('telegram')) {
      contacts.push([
        'telegram',
        { contact_type: 'telegram', init_data: platform.launch.rawInitData ?? '' },
      ]);
    }
    if (selected.includes('phone')) {
      // Telegram спрашивает про телефон до отправки чего-либо: отказ не оставит выбор отправленным
      // наполовину
      const response = await platform.shareContact();
      if (!response) {
        setNotSent(true);
        return;
      }
      contacts.push(['phone', { contact_type: 'phone', contact: response }]);
    }
    if (contacts.length === 0) return;
    const left = new Set(selected);
    for (const [value, contact] of contacts) {
      try {
        await share.mutateAsync(contact);
      } catch {
        // ушедшее снимается с выбора: «Поделиться» ещё раз не отправит его повторно
        setPicked(left);
        return;
      }
      left.delete(value);
    }
    setPicked(null);
    onClose();
  };

  return (
    <Sheet
      open={open}
      title={t('chat.share.title')}
      onClose={onClose}
      closeLabel={common('action.close')}
      footer={
        <Stack gap={8}>
          <Button
            full
            disabled={selected.length === 0 || busy}
            aria-busy={busy}
            onClick={() => void send()}
          >
            {t('chat.share.submit')}
          </Button>
          <Button variant="outline" full onClick={onClose}>
            {t('chat.share.later')}
          </Button>
        </Stack>
      }
    >
      <Stack gap={12}>
        {choices.length === 0 ? (
          <Banner tone="info">{t('chat.share.nothing')}</Banner>
        ) : (
          <>
            <Text variant="sm" secondary>
              {t('chat.share.text')}
            </Text>
            <div role="group" aria-label={t('chat.share.title')} className="flex flex-col gap-2">
              {choices.map((value) => (
                <Option
                  key={value}
                  kind="checkbox"
                  control="start"
                  title={
                    <span className="font-semibold">
                      {value === 'telegram' ? t('chat.share.telegram') : t('chat.share.phone')}
                    </span>
                  }
                  description={
                    value === 'telegram' ? `@${username ?? ''}` : t('chat.share.phoneHint')
                  }
                  checked={checked.has(value)}
                  onChange={(on) => toggle(value, on)}
                />
              ))}
            </div>
          </>
        )}
        <Banner tone="info" icon="lock">
          {t('chat.share.safety')}
        </Banner>
        {notSent && <Banner tone="info">{t('chat.share.notSent')}</Banner>}
        {share.error && (
          <Banner tone="danger" role="alert">
            {share.error instanceof ApiError && share.error.status < 500
              ? (share.error.problem.detail ?? t('chat.share.failed'))
              : t('chat.share.failed')}
          </Banner>
        )}
      </Stack>
    </Sheet>
  );
}
