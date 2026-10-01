// Удаление аккаунта S45 (DEVELOPMENT_PLAN 2.12a): запрос и отмена. Дата удаления сразу ложится в
// кэш /me: S31 показывает её и «Отменить» без перечитывания.
import type { MeOut } from '@sosed/api-client';
import {
  getIdentityGetMeQueryKey,
  identityCancelDeletion,
  identityRequestDeletion,
} from '@sosed/api-client';
import type { QueryClient } from '@tanstack/react-query';
import { useMutation, useQueryClient } from '@tanstack/react-query';

function scheduled(queryClient: QueryClient, at: string | null) {
  queryClient.setQueryData<MeOut>(getIdentityGetMeQueryKey(), (me) =>
    me ? { ...me, deletion_scheduled_at: at } : me,
  );
}

/** Удалить аккаунт через 7 дней; повтор — тот же срок. */
export function useRequestDeletion() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => identityRequestDeletion(),
    onSuccess: (deletion) => scheduled(queryClient, deletion.execute_after),
  });
}

/** Отменить удаление; запроса не было — тоже успех. */
export function useCancelDeletion() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => identityCancelDeletion(),
    onSuccess: () => scheduled(queryClient, null),
  });
}
