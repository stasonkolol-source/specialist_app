// Диалоги (DEVELOPMENT_PLAN 6.4): список S29 страницами по курсору, вкладки «Я клиент» и «Я
// исполнитель» — фильтр роли. «Написать» (S08, S24) начинает диалог или открывает уже начатый.
// Бейджи таббара — новые отклики и непрочитанные сообщения: при открытии, при возврате в
// приложение и раз в минуту; гостю — без запросов.
import type {
  ConversationOut,
  ConversationStartIn,
  ConversationsPageOut,
  ParticipantRole,
} from '@sosed/api-client';
import {
  getMessagingListConversationsQueryKey,
  getSession,
  getViewsGetBadgesQueryKey,
  messagingListConversations,
  messagingStartConversation,
  viewsGetBadges,
} from '@sosed/api-client';
import type { InfiniteData, QueryClient } from '@tanstack/react-query';
import {
  keepPreviousData,
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query';

export const CONVERSATIONS_PAGE_SIZE = 20;
export const BADGES_POLL_MS = 60_000;

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

/** Бейджи таббара: «Заявки N» (новые отклики) и «Сообщения N» (непрочитанные). */
export function useBadges() {
  return useQuery({
    queryKey: getViewsGetBadgesQueryKey(),
    queryFn: ({ signal }) => viewsGetBadges({ signal }),
    enabled: getSession() !== null,
    refetchInterval: BADGES_POLL_MS,
    refetchOnWindowFocus: true,
  });
}

/** Прочитали или написали — бейдж и список S29 перечитываются. */
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
    onSuccess: () => refreshInbox(client),
  });
}

/** Подпись сделки диалога для S29 и шапки S30: нет сделки — «ещё не договорились». */
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
