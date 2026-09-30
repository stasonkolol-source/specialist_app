import type { NotificationOut, NotificationPageOut } from '@sosed/api-client';
import { configureApiClient } from '@sosed/api-client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { describe, expect, it, vi } from 'vitest';

import type { NotificationFeed } from './notifications.ts';
import {
  feedItems,
  groupByDay,
  markRead,
  notificationsQueryKey,
  unreadCount,
  useMarkNotificationsRead,
  useNotificationFeed,
} from './notifications.ts';

const note = (id: string, createdAt: string, read = false): NotificationOut => ({
  id,
  type: 'system.test',
  title: `Заголовок ${id}`,
  body: 'Текст',
  link: null,
  created_at: createdAt,
  read,
});

const page = (items: NotificationOut[], unread: number, next: string | null = null) =>
  ({ items, unread_count: unread, next_cursor: next }) satisfies NotificationPageOut;

const feedOf = (...pages: NotificationPageOut[]): NotificationFeed => ({
  pages,
  pageParams: pages.map((_, index) => (index === 0 ? null : `c${index}`)),
});

function setup(respond: (url: URL, init?: RequestInit) => Response | Promise<Response>) {
  const fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) =>
    respond(new URL(String(input), 'http://api.test'), init),
  );
  configureApiClient({ fetch, locale: () => 'ru' });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return { fetch, client, wrapper };
}

describe('markRead', () => {
  const feed = feedOf(
    page([note('a', '2026-10-02T10:00:00Z'), note('b', '2026-10-02T09:00:00Z', true)], 3, 'c1'),
    page([note('c', '2026-10-01T09:00:00Z')], 3),
  );

  it('marks the given ids on every page and lowers the counter by what changed', () => {
    const next = markRead(feed, { ids: ['a', 'b', 'c'] });
    expect(feedItems(next).map((item) => item.read)).toEqual([true, true, true]);
    expect(unreadCount(next)).toBe(1); // «b» уже был прочитан, третий непрочитанный — не загружен
    expect(next.pages.map((p) => p.unread_count)).toEqual([1, 1]);
  });

  it('«all» marks everything and zeroes the counter', () => {
    const next = markRead(feed, { all: true });
    expect(feedItems(next).every((item) => item.read)).toBe(true);
    expect(unreadCount(next)).toBe(0);
    expect(feedItems(feed).map((item) => item.read)).toEqual([false, true, false]); // без мутаций
  });
});

describe('groupByDay', () => {
  it('today, yesterday, then by date — by the device clock', () => {
    const now = new Date(2026, 9, 2, 18, 7);
    const at = (day: number, hour: number) => new Date(2026, 9, day, hour).toISOString();
    const days = groupByDay(
      [note('1', at(2, 18)), note('2', at(2, 0)), note('3', at(1, 23)), note('4', at(28, 9))].slice(
        0,
        3,
      ),
      now,
    );
    expect(days.map((day) => [day.key, day.items.map((item) => item.id)])).toEqual([
      ['today', ['1', '2']],
      ['yesterday', ['3']],
    ]);
    const older = groupByDay([note('5', new Date(2026, 8, 28, 9).toISOString())], now);
    expect(older).toMatchObject([{ key: 'earlier', date: new Date(2026, 8, 28) }]);
  });
});

describe('useNotificationFeed', () => {
  it('pages by cursor and keys the feed by language', async () => {
    const { fetch, wrapper, client } = setup((url) =>
      Response.json(
        url.searchParams.get('cursor') === 'c1'
          ? page([note('b', '2026-10-01T09:00:00Z')], 1)
          : page([note('a', '2026-10-02T09:00:00Z')], 1, 'c1'),
      ),
    );
    const { result } = renderHook(() => useNotificationFeed('ru'), { wrapper });
    await waitFor(() => expect(result.current.data?.pages).toHaveLength(1));
    expect(result.current.hasNextPage).toBe(true);

    act(() => void result.current.fetchNextPage());

    await waitFor(() => expect(result.current.data?.pages).toHaveLength(2));
    expect(feedItems(result.current.data).map((item) => item.id)).toEqual(['a', 'b']);
    expect(result.current.hasNextPage).toBe(false);
    expect(fetch.mock.calls.map(([url]) => new URL(String(url), 'http://api.test').search)).toEqual(
      ['?limit=20', '?limit=20&cursor=c1'],
    );
    expect(client.getQueryData(notificationsQueryKey('ru'))).toBeTruthy();
    expect(client.getQueryData(notificationsQueryKey('sr-Latn'))).toBeUndefined();
  });
});

describe('useMarkNotificationsRead', () => {
  it('shows «read» at once and takes the counter from the answer', async () => {
    let release: () => void = () => {};
    const answered = new Promise<void>((resolve) => (release = resolve));
    const { client, wrapper } = setup(async () => {
      await answered;
      return Response.json({ unread_count: 4 });
    });
    const key = notificationsQueryKey('ru');
    client.setQueryData(key, feedOf(page([note('a', '2026-10-02T09:00:00Z')], 5)));
    const { result } = renderHook(() => useMarkNotificationsRead('ru'), { wrapper });

    act(() => result.current.mutate({ ids: ['a'] }));

    await waitFor(() => expect(unreadCount(client.getQueryData(key))).toBe(4));
    expect(feedItems(client.getQueryData(key))[0]?.read).toBe(true);
    release();
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(unreadCount(client.getQueryData(key))).toBe(4);
  });

  it('rolls back when the server did not take it', async () => {
    const { client, wrapper } = setup(() =>
      Response.json(
        { type: 'about:blank', title: 'x', status: 500, code: 'internal', trace_id: 't' },
        { status: 500, headers: { 'Content-Type': 'application/problem+json' } },
      ),
    );
    const key = notificationsQueryKey('ru');
    const before = feedOf(page([note('a', '2026-10-02T09:00:00Z')], 1));
    client.setQueryData(key, before);
    const { result } = renderHook(() => useMarkNotificationsRead('ru'), { wrapper });

    act(() => result.current.mutate({ all: true }));

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(client.getQueryData(key)).toEqual(before);
  });
});
