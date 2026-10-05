import type {
  BlocksOut,
  FavoritesOut,
  SpecialistCardOut,
  SpecialistPageOut,
} from '@sosed/api-client';
import {
  configureApiClient,
  getSearchListFavoritesQueryKey,
  getSearchListSpecialistsQueryKey,
  setSession,
} from '@sosed/api-client';
import type { InfiniteData } from '@tanstack/react-query';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { blockedUserOf, blocksQueryKey, shortName, useToggleBlock } from './blocks.ts';
import { allowedReason, reportQueue } from './reports.ts';

const card = (id: string): SpecialistCardOut => ({
  profile_id: id,
  display_name: `Мастер ${id}`,
  headline: null,
  kind: 'pro',
  avatar: null,
  district: null,
  whole_city: false,
  distance_m: null,
  languages: [],
  category_ids: [],
  price_from: null,
  price_from_unit: null,
  negotiable: false,
  rating: null,
  rating_count: 0,
  is_new: true,
  available_until: null,
  badges: [],
});

const page = (...ids: string[]): SpecialistPageOut =>
  ({
    items: ids.map(card),
    next_cursor: null,
    total: null,
    stage: 'browse',
    hints: [],
    category_ids: [],
    did_you_mean: null,
  }) as unknown as SpecialistPageOut;

const json = (body: unknown, status = 200) =>
  new Response(status === 204 ? null : JSON.stringify(body), {
    status,
    headers: { 'Content-Type': status >= 400 ? 'application/problem+json' : 'application/json' },
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

function deferred() {
  let resolve!: (response: Response) => void;
  const promise = new Promise<Response>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

afterEach(() => setSession(null));

const RESULTS = [...getSearchListSpecialistsQueryKey({ city_id: 1 }), 'ru'];
const TODAY = [...getSearchListSpecialistsQueryKey({ city_id: 1, available_today: true }), 'ru'];
const FAVORITES = [...getSearchListFavoritesQueryKey(), 'ru'];
const ALEXEY = blockedUserOf({ user_id: 'u1', display_name: 'Алексей Морозов', profile_id: 'p1' });

describe('blocks', () => {
  it('убирает заблокированного из выдачи, «Свободны сегодня» и избранного сразу', async () => {
    setSession({ accessToken: 'a', refreshToken: 'r' });
    const answer = deferred();
    const { client, wrapper } = setup((_url, init) =>
      init?.method === 'PUT' ? answer.promise : json({ items: [] }),
    );
    client.setQueryData<InfiniteData<SpecialistPageOut>>(RESULTS, {
      pages: [page('p1', 'p2')],
      pageParams: [null],
    });
    client.setQueryData(TODAY, page('p1'));
    client.setQueryData<FavoritesOut>(FAVORITES, { items: [card('p1'), card('p3')] });
    const { result } = renderHook(() => useToggleBlock(), { wrapper });

    act(() => result.current.mutate({ user: ALEXEY, on: true }));

    await waitFor(() =>
      expect(client.getQueryData<BlocksOut>(blocksQueryKey())?.items).toEqual([ALEXEY]),
    );
    const results = client.getQueryData<InfiniteData<SpecialistPageOut>>(RESULTS);
    expect(results?.pages[0]?.items.map((item) => item.profile_id)).toEqual(['p2']);
    expect(client.getQueryData<SpecialistPageOut>(TODAY)?.items).toEqual([]);
    expect(
      client.getQueryData<FavoritesOut>(FAVORITES)?.items.map((item) => item.profile_id),
    ).toEqual(['p3']);
    answer.resolve(json(null, 204));
  });

  it('возвращает человека в список S44, если разблокировать не вышло', async () => {
    setSession({ accessToken: 'a', refreshToken: 'r' });
    const { client, wrapper } = setup((_url, init) =>
      init?.method === 'DELETE'
        ? json({ code: 'unavailable', status: 503 }, 503)
        : json({ items: [ALEXEY] }),
    );
    client.setQueryData<BlocksOut>(blocksQueryKey(), { items: [ALEXEY] });
    const { result } = renderHook(() => useToggleBlock(), { wrapper });

    act(() => result.current.mutate({ user: ALEXEY, on: false }));

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(client.getQueryData<BlocksOut>(blocksQueryKey())?.items).toEqual([ALEXEY]);
  });
});

describe('reports', () => {
  it('знает причины каждого типа и очередь по причине', () => {
    expect(allowedReason('profile', 'fraud')).toBe(true);
    expect(allowedReason('profile', 'no_show')).toBe(false);
    expect(allowedReason('user', 'no_show')).toBe(true);
    expect(reportQueue('offensive')).toBe('safety');
    expect(reportQueue('prohibited')).toBe('safety');
    expect(reportQueue('fraud')).toBe('fraud');
    expect(reportQueue('other')).toBe('fraud');
  });

  it('пишет имя, как сервер: имя и первая буква фамилии', () => {
    expect(shortName('Алексей Морозов')).toBe('Алексей М.');
    expect(shortName('Ana')).toBe('Ana');
    expect(ALEXEY.display_name).toBe('Алексей М.');
  });
});
