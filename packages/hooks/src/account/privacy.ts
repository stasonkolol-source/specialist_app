// «Показывать после договорённости» (S43; DEVELOPMENT_PLAN 6.5): свой Telegram второй стороне
// сделки. Ответ сервера — свежий /me: экраны, что читают его, видят новое значение сразу.
import type { PrivacyIn } from '@sosed/api-client';
import { getIdentityGetMeQueryKey, identityUpdatePrivacy } from '@sosed/api-client';
import { useMutation, useQueryClient } from '@tanstack/react-query';

export function useUpdatePrivacy() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (privacy: PrivacyIn) => identityUpdatePrivacy(privacy),
    onSuccess: (me) => client.setQueryData(getIdentityGetMeQueryKey(), me),
  });
}
