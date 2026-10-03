// То, что уже было на экране списка, — для шапки экрана подробностей, пока он грузится (S08 из
// выдачи S05, «Свободны сегодня» S03 и избранного S12; S15 из ленты S13 и сохранённых S12; S30 из
// диалогов S29). Только карточка списка, не ответ экрана: экран рисует из неё видимое (имя, фото,
// название, бюджет), а действия и закрытые поля — только по полному ответу.
import type { ConversationOut, JobCardOut, SpecialistCardOut } from '@sosed/api-client';
import {
  getJobsListSavedJobsQueryKey,
  getSearchListFavoritesQueryKey,
  getSearchListSpecialistsQueryKey,
} from '@sosed/api-client';
import type { QueryClient } from '@tanstack/react-query';

import { FEED_KEY } from './jobs/feed.ts';
import { CONVERSATIONS_KEY } from './messages/conversations.ts';

/** Список или страницы списка (useInfiniteQuery) — элементы подряд. */
type Listed<T> = { items: T[] } | { pages: { items: T[] }[] };

function find<T>(
  client: QueryClient,
  queryKeys: readonly (readonly unknown[])[],
  match: (item: T) => boolean,
): T | undefined {
  for (const queryKey of queryKeys) {
    for (const [, data] of client.getQueriesData<Listed<T>>({ queryKey })) {
      if (!data) continue;
      const items = 'pages' in data ? data.pages.flatMap((page) => page.items) : data.items;
      const found = items?.find(match);
      if (found) return found;
    }
  }
  return undefined;
}

/** Специалист из выдачи, «Свободны сегодня» или избранного. */
export function cachedSpecialistCard(
  client: QueryClient,
  profileId: string,
): SpecialistCardOut | undefined {
  return find<SpecialistCardOut>(
    client,
    [getSearchListSpecialistsQueryKey().slice(0, 1), getSearchListFavoritesQueryKey()],
    (card) => card.profile_id === profileId,
  );
}

/** Заявка из ленты или сохранённых. */
export function cachedJobCard(client: QueryClient, jobId: string): JobCardOut | undefined {
  return find<JobCardOut>(
    client,
    [FEED_KEY, getJobsListSavedJobsQueryKey()],
    (card) => card.id === jobId,
  );
}

/** Диалог из списка S29. */
export function cachedConversation(
  client: QueryClient,
  conversationId: string,
): ConversationOut | undefined {
  return find<ConversationOut>(client, [CONVERSATIONS_KEY], (item) => item.id === conversationId);
}
