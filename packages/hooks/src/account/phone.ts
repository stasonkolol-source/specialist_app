// «Подтвердить телефон» (S33, S32c, S43; ADR-0009): добровольный бейдж «Телефон подтверждён» одним
// нажатием. Telegram спрашивает человека и отдаёт подписанный ответ requestContact, backend
// проверяет подпись и что номер — этого аккаунта (POST /me/phone). Номер сервер не возвращает:
// в ответе — свежий /me с `phone_verified`, его и видят экраны. Клиент Telegram хук получает
// снаружи (packages/platform), как useBotChannel: хуки — без Telegram.
import { getIdentityGetMeQueryKey, identityVerifyPhone } from '@sosed/api-client';
import { useMutation, useQueryClient } from '@tanstack/react-query';

/** Что хуку нужно от клиента Telegram: умеет ли он отдать контакт и сам запрос. */
export interface PhoneContactClient {
  capabilities: { requestContact: boolean };
  /** Подписанный ответ requestContact; отказ или нет ответа — null. */
  shareContact(): Promise<string | null>;
}

/** Человек не отправил номер (или клиент не ответил): на сервер ничего не уходит. */
export class PhoneDeclinedError extends Error {
  constructor() {
    super('phone contact declined');
    this.name = 'PhoneDeclinedError';
  }
}

/** `available` — клиент умеет отдать контакт (в браузере и старом Telegram кнопки нет);
 *  `verify` — запрос: отказ — PhoneDeclinedError, занятый номер — ApiError 409 `phone_taken`. */
export function useVerifyPhone(client: PhoneContactClient) {
  const queryClient = useQueryClient();
  const verify = useMutation({
    mutationFn: async () => {
      const contact = await client.shareContact().catch(() => null);
      if (!contact) throw new PhoneDeclinedError();
      return identityVerifyPhone({ contact });
    },
    onSuccess: (me) => queryClient.setQueryData(getIdentityGetMeQueryKey(), me),
  });
  return { available: client.capabilities.requestContact, verify };
}
