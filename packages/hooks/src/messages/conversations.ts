// Диалоги (DEVELOPMENT_PLAN 6.4): список S29 страницами по курсору, вкладки «Я клиент» и «Я
// исполнитель» — фильтр роли. «Написать» (S08, S24) начинает диалог или открывает уже начатый.
// Бейджи таббара — в badges.ts: их читает оболочка первого экрана, а этот модуль — нет.
import type {
  ConversationOut,
  ConversationStartIn,
  ConversationsPageOut,
  ParticipantRole,
} from '@sosed/api-client';
import {
  getMessagingListConversationsQueryKey,
  getViewsGetBadgesQueryKey,
  messagingListConversations,
  messagingStartConversation,
} from '@sosed/api-client';
import type { InfiniteData, QueryClient } from '@tanstack/react-query';
import {
  keepPreviousData,
  useInfiniteQuery,
  useMutation,
  useQueryClient,
} from '@tanstack/react-query';

export const CONVERSATIONS_PAGE_SIZE = 20;

/** Вкладки S29: `null` — «Все». */
export type ChatRole = Extract<ParticipantRole, 'client' | 'performer'>;
export type ConversationPages = InfiniteData<ConversationsPageOut, string | null>;

/** Список с любой вкладкой. */
export const CONVERSATIONS_KEY = getMessagingListConversationsQueryKey().slice(0, 1);

export const conversationsQueryKey = (role: ChatRole | null) =>
  getMessagingListConversationsQueryKey(role ? { role } : undefined);

export function useConversations(role: ChatRole | null) {
  return useInfiniteQuery({
    queryKey: conversationsQueryKey(role),
    queryFn: ({ pageParam, signal }) =>
      messagingListConversations(
        {
          ...(role ? { role } : {}),
          limit: CONVERSATIONS_PAGE_SIZE,
          ...(pageParam ? { cursor: pageParam } : {}),
        },
        { signal },
      ),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor ?? null,
    placeholderData: keepPreviousData,
  });
}

/** Диалоги всех загруженных страниц подряд. */
export function conversationItems(pages: Pick<ConversationPages, 'pages'> | undefined) {
  return pages?.pages.flatMap((page) => page.items) ?? [];
}

/** Прочитали или написали — бейдж и список S29 перечитываются. Экран действия их не ждёт:
 *  вызывающие запускают перечитывание в фоне (`void`). */
export async function refreshInbox(client: QueryClient) {
  await Promise.all([
    client.invalidateQueries({ queryKey: getViewsGetBadgesQueryKey() }),
    client.invalidateQueries({ queryKey: CONVERSATIONS_KEY }),
  ]);
}

/** «Написать»: по отклику (`response_id`) или специалисту из карточки (`profile_id`). Диалог уже
 *  есть — сервер вернёт его же. */
export function useStartConversation() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (target: ConversationStartIn) => messagingStartConversation(target),
    // диалог S30 открывается сразу, бейджи и список S29 — в фоне
    onSuccess: () => void refreshInbox(client),
  });
}

/** Подпись сделки диалога для S29 и шапки S30: нет сделки — «Сделки пока нет». */
export type DealState = 'none' | 'proposed' | 'agreed' | 'completed' | 'cancelled' | 'disputed';

export function dealState(conversation: Pick<ConversationOut, 'deal'>): DealState {
  const status = conversation.deal?.status;
  switch (status) {
    case 'proposed':
    case 'agreed':
    case 'completed':
    case 'cancelled':
    case 'disputed':
      return status;
    default:
      return 'none';
  }
}
