// S54 «Поделиться контактом» (DEVELOPMENT_PLAN 6.5; ADR-0010): после договорённости сторона сама
// выбирает, что отправить — имя пользователя Telegram (если оно есть и «Мой Telegram» включён в
// настройках) или телефон (Telegram спросит подтверждение и отдаст подписанный номер). Контакт
// уходит собеседнику сообщением в чате. Памятка: никому не сообщать коды из SMS и данные карты.
import type { ContactShareIn, MeOut } from '@sosed/api-client';
import { ApiError, getIdentityGetMeQueryKey } from '@sosed/api-client';
import { useShareContact } from '@sosed/hooks';
import { useTranslation } from '@sosed/i18n';
import { usePlatform } from '@sosed/platform';
import { Banner, Button, LinkButton, Option, RadioGroup, Sheet, Stack, Text } from '@sosed/ui-web';
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
  const [picked, setPicked] = useState<Choice | null>(null);
  const choice = picked ?? choices[0] ?? null;
  const busy = share.isPending;

  const send = async () => {
    setNotSent(false);
    let contact: ContactShareIn;
    if (choice === 'telegram') {
      contact = { contact_type: 'telegram', init_data: platform.launch.rawInitData ?? '' };
    } else if (choice === 'phone') {
      const response = await platform.shareContact();
      if (!response) {
        setNotSent(true);
        return;
      }
      contact = { contact_type: 'phone', contact: response };
    } else return;
    share.mutate(contact, { onSuccess: onClose });
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
            disabled={choice === null || busy}
            aria-busy={busy}
            onClick={() => void send()}
          >
            {t('chat.share.submit')}
          </Button>
          <LinkButton onClick={onClose}>{t('chat.share.later')}</LinkButton>
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
            <RadioGroup label={t('chat.share.title')}>
              {choices.map((value) => (
                <Option
                  key={value}
                  icon={value === 'telegram' ? 'send' : 'phone'}
                  title={value === 'telegram' ? t('chat.share.telegram') : t('chat.share.phone')}
                  description={
                    value === 'telegram' ? `@${username ?? ''}` : t('chat.share.phoneHint')
                  }
                  checked={choice === value}
                  onChange={() => setPicked(value)}
                />
              ))}
            </RadioGroup>
          </>
        )}
        <Banner tone="warn" icon="shield">
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
