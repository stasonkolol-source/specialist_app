// Последнее сообщение строкой списка S29: своё — «Вы: …», контакт, скрытое и удалённое — словами,
// что со сделкой — словами системного события. Отклик — текстом: что это отклик, говорит плашка
// «Отклик» строки.
import type { MessageOut } from '@sosed/api-client';
import { useTranslation } from '@sosed/i18n';

export function usePreview() {
  const { t } = useTranslation('messages');
  return (message: MessageOut | null | undefined): string => {
    if (!message) return '';
    let text: string;
    if (message.kind === 'system') {
      const type = message.event?.type;
      // отменили предложение, а не сделку — «Предложение не принято» (UX_GUIDANCE №14)
      text =
        type === 'deal_agreed'
          ? t('preview.dealAgreed')
          : type === 'deal_cancelled'
            ? t(message.event?.proposal ? 'preview.dealDeclined' : 'preview.dealCancelled')
            : t('preview.dealProposed');
      return text;
    }
    if (message.kind === 'contact_share') text = t('preview.contact');
    else if (message.hidden && !message.mine) text = t('preview.hidden');
    else if (message.body === null) text = t('preview.erased');
    else text = message.body;
    return message.mine ? t('list.you', { text }) : text;
  };
}
