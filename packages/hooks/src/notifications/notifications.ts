// Центр уведомлений S42 (DEVELOPMENT_PLAN 4.9, API 2.3a): лента по курсору, «прочитано», счётчик
// непрочитанных для строки S31. Заголовок и текст приходят на языке запроса (Accept-Language),
// поэтому язык — часть ключа: после смены языка лента перечитывается.
// «Прочитано» видно сразу (оптимистично), ответ сервера уточняет счётчик; ошибка — откат.
import type {
  Locale,
  NotificationOut,
  NotificationPageOut,
  NotificationsReadIn,
} from '@sosed/api-client';
import {
  getNotificationsListNotificationsQueryKey,
  notificationsListNotifications,
  notificationsMarkNotificationsRead,
} from '@sosed/api-client';
import type { InfiniteData } from '@tanstack/react-query';
import { useInfiniteQuery, useMutation, useQueryClient } from '@tanstack/react-query';

export const NOTIFICATIONS_PAGE_SIZE = 20;

export type NotificationFeed = InfiniteData<NotificationPageOut, string | null>;

export function notificationsQueryKey(locale: Locale) {
  return [...getNotificationsListNotificationsQueryKey(), 'feed', locale] as const;
}

export function useNotificationFeed(
  locale: Locale,
  { enabled = true }: { enabled?: boolean } = {},
) {
  return useInfiniteQuery({
    queryKey: notificationsQueryKey(locale),
    queryFn: ({ pageParam, signal }) =>
      notificationsListNotifications(
        pageParam === null
          ? { limit: NOTIFICATIONS_PAGE_SIZE }
          : { limit: NOTIFICATIONS_PAGE_SIZE, cursor: pageParam },
        { signal },
      ),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor ?? null,
    enabled,
  });
}

/** Загруженные страницы ленты — всё, что нужно функциям ниже. */
type Pages = Pick<NotificationFeed, 'pages'>;

/** Уведомления всех загруженных страниц подряд, новые сверху. */
export function feedItems(feed: Pages | undefined): NotificationOut[] {
  return feed?.pages.flatMap((page) => page.items) ?? [];
}

/** Непрочитанные по данным сервера: счётчик приходит с каждой страницей, свежий — в первой. */
export function unreadCount(feed: Pages | undefined): number {
  return feed?.pages[0]?.unread_count ?? 0;
}

/** Отметить прочитанными `ids` или всё (`all`) — в кэше ленты, до ответа сервера. */
export function markRead(feed: NotificationFeed, body: NotificationsReadIn): NotificationFeed {
  const ids = body.all ? null : new Set(body.ids ?? []);
  let marked = 0;
  const pages = feed.pages.map((page) => ({
    ...page,
    items: page.items.map((item) => {
      if (item.read || (ids && !ids.has(item.id))) return item;
      marked += 1;
      return { ...item, read: true };
    }),
  }));
  const unread = body.all ? 0 : Math.max(0, unreadCount(feed) - marked);
  return withUnread({ ...feed, pages }, unread);
}

function withUnread(feed: NotificationFeed, unread: number): NotificationFeed {
  return { ...feed, pages: feed.pages.map((page) => ({ ...page, unread_count: unread })) };
}

export function useMarkNotificationsRead(locale: Locale) {
  const client = useQueryClient();
  const key = notificationsQueryKey(locale);
  return useMutation({
    mutationFn: (body: NotificationsReadIn) => notificationsMarkNotificationsRead(body),
    onMutate: async (body) => {
      await client.cancelQueries({ queryKey: key });
      const previous = client.getQueryData<NotificationFeed>(key);
      if (previous) client.setQueryData<NotificationFeed>(key, markRead(previous, body));
      return { previous };
    },
    onError: (_error, _body, context) => {
      if (context?.previous) client.setQueryData(key, context.previous);
    },
    onSuccess: (result) => {
      client.setQueryData<NotificationFeed>(
        key,
        (feed) => feed && withUnread(feed, result.unread_count),
      );
    },
  });
}

export type DayKey = 'today' | 'yesterday' | 'earlier';

export interface NotificationDay {
  /** Сегодня, вчера или раньше (тогда подпись — дата `date`). */
  key: DayKey;
  /** Полночь дня по часам устройства — для подписи и React key. */
  date: Date;
  items: NotificationOut[];
}

/** Уведомления по дням (часы устройства): «Сегодня», «Вчера», дальше — по дате. */
export function groupByDay(items: readonly NotificationOut[], now: Date): NotificationDay[] {
  const today = midnight(now).getTime();
  const days: NotificationDay[] = [];
  for (const item of items) {
    const date = midnight(new Date(item.created_at));
    const last = days.at(-1);
    if (last && last.date.getTime() === date.getTime()) {
      last.items.push(item);
      continue;
    }
    const diff = Math.round((today - date.getTime()) / 86_400_000);
    const key: DayKey = diff <= 0 ? 'today' : diff === 1 ? 'yesterday' : 'earlier';
    days.push({ key, date, items: [item] });
  }
  return days;
}

function midnight(date: Date): Date {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate());
}
