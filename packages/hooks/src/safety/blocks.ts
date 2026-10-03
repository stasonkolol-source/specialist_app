// Блокировки (DEVELOPMENT_PLAN 4.7): список S44 и строка S43 — из одного GET /me/blocks; меню S08
// и S30 знают по нему, заблокирован ли человек. Заблокировать — сразу (оптимистично): человек
// пропадает из загруженных выдачи S05, «Свободны сегодня» и избранного S12, ошибка возвращает как
// было; ленты, счётчики и переписка перечитываются в фоне — их фильтрует сервер. Гостю блокировок
// нет: без сессии запроса нет.
import type {
  BlockedUserOut,
  BlocksOut,
  FavoritesOut,
  SpecialistCardOut,
  SpecialistPageOut,
} from '@sosed/api-client';
import {
  getJobsCountJobsQueryKey,
  getJobsListJobsQueryKey,
  getJobsListSavedJobsQueryKey,
  getMessagingListConversationsQueryKey,
  getSearchCountSpecialistsQueryKey,
  getSearchListFavoritesQueryKey,
  getSearchListSpecialistsQueryKey,
  getSession,
  getViewsListBlocksQueryKey,
  identityBlockUser,
  identityUnblockUser,
  viewsListBlocks,
} from '@sosed/api-client';
import type { InfiniteData, QueryClient } from '@tanstack/react-query';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { OWN_STALE_MS } from '../cache.ts';

export const blocksQueryKey = () => getViewsListBlocksQueryKey();

export function useBlocks() {
  return useQuery({
    queryKey: blocksQueryKey(),
    queryFn: ({ signal }) => viewsListBlocks({ signal }),
    enabled: getSession() !== null,
    staleTime: OWN_STALE_MS,
  });
}

/** id заблокированных мною — для меню S08 и S30 («Заблокировать» или «Разблокировать»). */
export function blockedIds(out: BlocksOut | undefined): ReadonlySet<string> {
  return new Set(out?.items.map((item) => item.user_id) ?? []);
}

export interface BlockToggle {
  /** Кого: имя и фото — встать в начало списка S44 до ответа сервера. */
  user: BlockedUserOut;
  on: boolean;
}

/** Имя и первая буква фамилии, как в ответе сервера: «Алексей Морозов» → «Алексей М.». */
export function shortName(name: string): string {
  const [first = '', ...rest] = name.trim().split(/\s+/);
  const last = rest.at(-1);
  return last ? `${first} ${last.charAt(0).toUpperCase()}.` : first;
}

/** Строка S44 из того, что экран уже знает (карточка S08, шапка S30): до ответа сервера. */
export function blockedUserOf(
  user: Pick<BlockedUserOut, 'user_id' | 'display_name'> & Partial<BlockedUserOut>,
): BlockedUserOut {
  return {
    avatar: null,
    profile_id: null,
    blocked_at: new Date().toISOString(),
    ...user,
    display_name: shortName(user.display_name),
  };
}

export function useToggleBlock() {
  const client = useQueryClient();
  const key = blocksQueryKey();
  return useMutation({
    mutationFn: ({ user, on }: BlockToggle) =>
      on ? identityBlockUser(user.user_id) : identityUnblockUser(user.user_id),
    onMutate: async ({ user, on }) => {
      await client.cancelQueries({ queryKey: key });
      const before = client.getQueryData<BlocksOut>(key);
      client.setQueryData<BlocksOut>(key, (old) => {
        const items = (old?.items ?? []).filter((item) => item.user_id !== user.user_id);
        return { items: on ? [user, ...items] : items };
      });
      if (on && user.profile_id) hideProfile(client, user.profile_id);
      return { before };
    },
    onError: (_error, { user }, context) => {
      if (!context) return;
      client.setQueryData<BlocksOut>(key, (old) => {
        if (!old) return old;
        // откатываем только этого человека: соседние действия могли уже завершиться
        const items = old.items.filter((item) => item.user_id !== user.user_id);
        const index = context.before?.items.findIndex((i) => i.user_id === user.user_id) ?? -1;
        const previous = context.before?.items[index];
        if (previous) items.splice(index, 0, previous);
        return { items };
      });
      // скрытая оптимистично карточка вернётся с перечитанной выдачей
      if (user.profile_id) void refreshCatalog(client);
    },
    // список уже поправлен; выдача, ленты и переписка — сверка с сервером в фоне
    onSettled: () => {
      void client.invalidateQueries({ queryKey: key });
      void refreshCatalog(client);
      void refreshJobs(client);
      void client.invalidateQueries({ queryKey: getMessagingListConversationsQueryKey() });
      void client.invalidateQueries({ predicate: (query) => isChat(query.queryKey[0]) });
    },
  });
}

/** Ключ ленты диалога S30 — `/api/v1/conversations/{id}/messages`: блокировка меняет её шапку. */
const isChat = (head: unknown) =>
  typeof head === 'string' &&
  head.startsWith('/api/v1/conversations/') &&
  head.endsWith('/messages');

type SearchCache = InfiniteData<SpecialistPageOut, string | null> | SpecialistPageOut;

const without = (items: SpecialistCardOut[], profileId: string) =>
  items.filter((card) => card.profile_id !== profileId);

/** Убрать специалиста из загруженных выдач (страницы S05 и «Свободны сегодня» S03) и избранного. */
function hideProfile(client: QueryClient, profileId: string) {
  client.setQueriesData<SearchCache>(
    { queryKey: getSearchListSpecialistsQueryKey().slice(0, 1) },
    (data) => {
      if (!data) return data;
      if ('pages' in data) {
        return {
          ...data,
          pages: data.pages.map((page) => ({ ...page, items: without(page.items, profileId) })),
        };
      }
      return { ...data, items: without(data.items, profileId) };
    },
  );
  client.setQueriesData<FavoritesOut>({ queryKey: getSearchListFavoritesQueryKey() }, (data) =>
    data ? { items: without(data.items, profileId) } : data,
  );
}

async function refreshCatalog(client: QueryClient) {
  await Promise.all([
    client.invalidateQueries({ queryKey: getSearchListSpecialistsQueryKey().slice(0, 1) }),
    client.invalidateQueries({ queryKey: getSearchCountSpecialistsQueryKey().slice(0, 1) }),
    client.invalidateQueries({ queryKey: getSearchListFavoritesQueryKey() }),
  ]);
}

async function refreshJobs(client: QueryClient) {
  await Promise.all([
    client.invalidateQueries({ queryKey: getJobsListJobsQueryKey().slice(0, 1) }),
    client.invalidateQueries({ queryKey: getJobsCountJobsQueryKey().slice(0, 1) }),
    client.invalidateQueries({ queryKey: getJobsListSavedJobsQueryKey() }),
  ]);
}
