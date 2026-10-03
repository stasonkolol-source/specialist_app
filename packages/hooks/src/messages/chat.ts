// Диалог S30 (DEVELOPMENT_PLAN 6.4; ARCHITECTURE §11.6): последние сообщения опрашиваются раз в
// 4 с, пока экран открыт (тот же адрес — браузер переспрашивает по ETag, сервер отвечает 304);
// «Показать раньше» — страницы назад от первого показа. Всё, что пришло, копится по id: окно
// последних сдвигается, а показанное не пропадает. Отправка оптимистична: сообщение сразу в ленте
// («отправляется»), ошибка — «не отправлено, повторить» с тем же `client_msg_id`, поэтому повтор
// не создаёт второго. Новое от собеседника отмечается прочитанным, пока экран на виду.
import type {
  ContactShareIn,
  DealProposalIn,
  MessageOut,
  MessagesPageOut,
} from '@sosed/api-client';
import {
  getMessagingListMessagesQueryKey,
  messagingListMessages,
  messagingProposeDeal,
  messagingReadConversation,
  messagingSendMessage,
  messagingShareContact,
} from '@sosed/api-client';
import {
  queryOptions,
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query';
import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from 'react';

import { refreshInbox } from './conversations.ts';

export const CHAT_POLL_MS = 4_000;
export const CHAT_PAGE_SIZE = 50;
/** Сервер принимает до 4000 знаков (MessageIn.body). */
export const MAX_MESSAGE = 4000;

export interface PendingMessage {
  clientMsgId: string;
  body: string;
  createdAt: string;
  failed: boolean;
}

export type ChatEntry =
  { type: 'message'; message: MessageOut } | { type: 'pending'; pending: PendingMessage };

interface ChatState {
  messages: ReadonlyMap<string, MessageOut>;
  pending: readonly PendingMessage[];
}

type ChatAction =
  | { type: 'merge'; items: readonly MessageOut[] }
  | { type: 'pending'; pending: PendingMessage }
  | { type: 'sent'; clientMsgId: string; message: MessageOut }
  | { type: 'failed'; clientMsgId: string }
  | { type: 'retry'; clientMsgId: string };

const EMPTY: ChatState = { messages: new Map(), pending: [] };

function chatReducer(state: ChatState, action: ChatAction): ChatState {
  switch (action.type) {
    case 'merge': {
      if (action.items.length === 0) return state;
      const messages = new Map(state.messages);
      for (const item of action.items) messages.set(item.id, item);
      return { ...state, messages };
    }
    case 'pending':
      return { ...state, pending: [...state.pending, action.pending] };
    case 'sent': {
      const messages = new Map(state.messages);
      messages.set(action.message.id, action.message);
      const pending = state.pending.filter((item) => item.clientMsgId !== action.clientMsgId);
      return { messages, pending };
    }
    case 'failed':
    case 'retry':
      return {
        ...state,
        pending: state.pending.map((item) =>
          item.clientMsgId === action.clientMsgId
            ? { ...item, failed: action.type === 'failed' }
            : item,
        ),
      };
  }
}

/** Последняя страница диалога — её опрашивает S30. */
export const chatQueryKey = (conversationId: string) =>
  getMessagingListMessagesQueryKey(conversationId, { limit: CHAT_PAGE_SIZE });

/** Сообщения по порядку: UUIDv7 растёт со временем, строки сравниваются так же. */
function ordered(messages: ReadonlyMap<string, MessageOut>): MessageOut[] {
  return [...messages.values()].sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
}

/** Последняя страница диалога — у S30 и у предзагрузки по нажатию на диалог в S29. */
export function chatQueryOptions(conversationId: string) {
  return queryOptions({
    queryKey: chatQueryKey(conversationId),
    queryFn: ({ signal }) =>
      messagingListMessages(conversationId, { limit: CHAT_PAGE_SIZE }, { signal }),
  });
}

export function useChat(conversationId: string) {
  const client = useQueryClient();
  const latest = useQuery({ ...chatQueryOptions(conversationId), refetchInterval: CHAT_POLL_MS });
  // курсор «раньше» первого показа: дальше страницы идут от него
  const [anchor, setAnchor] = useState<string | null>(null);
  const earlier = useInfiniteQuery({
    queryKey: [...chatQueryKey(conversationId), 'earlier', anchor],
    queryFn: ({ pageParam, signal }) =>
      messagingListMessages(
        conversationId,
        { limit: CHAT_PAGE_SIZE, direction: 'older', cursor: pageParam },
        { signal },
      ),
    initialPageParam: anchor ?? '',
    getNextPageParam: (last: MessagesPageOut) => last.older_cursor ?? null,
    enabled: anchor !== null,
  });
  const [state, dispatch] = useReducer(chatReducer, EMPTY);

  useEffect(() => {
    if (latest.data) dispatch({ type: 'merge', items: latest.data.items });
  }, [latest.data]);
  useEffect(() => {
    for (const page of earlier.data?.pages ?? []) dispatch({ type: 'merge', items: page.items });
  }, [earlier.data]);

  const messages = useMemo(() => ordered(state.messages), [state.messages]);
  const entries = useMemo<ChatEntry[]>(
    () => [
      ...messages.map((message) => ({ type: 'message' as const, message })),
      ...state.pending.map((pending) => ({ type: 'pending' as const, pending })),
    ],
    [messages, state.pending],
  );

  const firstOlder = latest.data?.older_cursor ?? null;
  const hasEarlier = anchor === null ? firstOlder !== null : earlier.hasNextPage;
  const loadEarlier = useCallback(() => {
    if (anchor === null) {
      if (firstOlder !== null) setAnchor(firstOlder);
      return;
    }
    if (earlier.hasNextPage && !earlier.isFetchingNextPage) void earlier.fetchNextPage();
  }, [anchor, earlier, firstOlder]);

  const send = useMutation({
    mutationFn: (pending: PendingMessage) =>
      messagingSendMessage(conversationId, {
        body: pending.body,
        client_msg_id: pending.clientMsgId,
      }),
    onSuccess: (message, pending) => {
      dispatch({ type: 'sent', clientMsgId: pending.clientMsgId, message });
      void refreshInbox(client);
    },
    onError: (_error, pending) => dispatch({ type: 'failed', clientMsgId: pending.clientMsgId }),
  });

  const sendText = useCallback(
    (text: string) => {
      const body = text.trim();
      if (!body) return;
      const pending: PendingMessage = {
        clientMsgId: crypto.randomUUID(),
        body,
        createdAt: new Date().toISOString(),
        failed: false,
      };
      dispatch({ type: 'pending', pending });
      send.mutate(pending);
    },
    [send],
  );
  const retry = useCallback(
    (clientMsgId: string) => {
      const pending = state.pending.find((item) => item.clientMsgId === clientMsgId);
      if (!pending) return;
      dispatch({ type: 'retry', clientMsgId });
      send.mutate({ ...pending, failed: false });
    },
    [send, state.pending],
  );

  // прочитано: новое от собеседника, пока экран на виду
  const unread = latest.data?.conversation.unread ?? 0;
  const newest = messages.at(-1)?.id ?? null;
  const reported = useRef<string | null>(null);
  useEffect(() => {
    if (newest === null || unread === 0 || document.visibilityState !== 'visible') return;
    if (reported.current !== null && reported.current >= newest) return;
    reported.current = newest;
    messagingReadConversation(conversationId, { message_id: newest })
      .then(() => refreshInbox(client))
      .catch(() => {
        reported.current = null; // повторим со следующим опросом
      });
  }, [client, conversationId, newest, unread]);

  return {
    conversation: latest.data?.conversation,
    entries,
    isPending: latest.isPending,
    error: latest.error,
    hasEarlier,
    loadingEarlier: earlier.isFetching,
    loadEarlier,
    send: sendText,
    retry,
    sendError: send.error,
  };
}

/** «Договорились» в прямом диалоге: условия уходят второй стороне на подтверждение (S53). */
export function useProposeDeal(conversationId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (terms: DealProposalIn) => messagingProposeDeal(conversationId, terms),
    // человек остаётся в диалоге: ждём только его (сделка в шапке); бейджи и S29 — в фоне
    onSuccess: async () => {
      void refreshInbox(client);
      await client.invalidateQueries({ queryKey: chatQueryKey(conversationId) });
    },
  });
}

/** «Поделиться контактом» (S54): username Telegram — по initData, телефон — подписанным ответом
 *  Telegram; контакт уходит второй стороне сообщением в диалоге. */
export function useShareContact(conversationId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (contact: ContactShareIn) => messagingShareContact(conversationId, contact),
    onSuccess: async () => {
      void refreshInbox(client);
      await client.invalidateQueries({ queryKey: chatQueryKey(conversationId) });
    },
  });
}
