// Последнее сообщение строкой списка S29: своё — «Вы: …», отклик — «Отклик: …», контакт, скрытое и
// удалённое — словами, что со сделкой — словами системного события.
import type { MessageOut } from '@sosed/api-client';
import { useTranslation } from '@sosed/i18n';

export function usePreview() {
  const { t } = useTranslation('messages');
  return (message: MessageOut | null | undefined): string => {
    if (!message) return '';
    let text: string;
    if (message.kind === 'system') {
      const type = message.event?.type;
      text =
        type === 'deal_agreed'
          ? t('preview.dealAgreed')
          : type === 'deal_cancelled'
            ? t('preview.dealCancelled')
            : t('preview.dealProposed');
      return text;
    }
    if (message.kind === 'contact_share') text = t('preview.contact');
    else if (message.hidden && !message.mine) text = t('preview.hidden');
    else if (message.body === null) text = t('preview.erased');
    else if (message.kind === 'offer') text = t('preview.offer', { text: message.body });
    else text = message.body;
    return message.mine ? t('list.you', { text }) : text;
  };
}
