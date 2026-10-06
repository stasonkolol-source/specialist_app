import type { FavoritesOut, SpecialistCardOut } from '@sosed/api-client';
import { configureApiClient, setSession } from '@sosed/api-client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { favoriteIds, favoritesQueryKey, useFavorites, useToggleFavorite } from './favorites.ts';

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

afterEach(() => setSession(null));

const useBoth = () => ({ list: useFavorites('ru'), toggle: useToggleFavorite('ru') });

const ids = (client: QueryClient) => [
  ...favoriteIds(client.getQueryData<FavoritesOut>(favoritesQueryKey('ru'))),
];

/** Ответ сервера, который приходит, когда тест скажет: видно состояние до него. */
function deferred() {
  let resolve!: (response: Response) => void;
  const promise = new Promise<Response>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

describe('favorites', () => {
  it('не восстанавливает отклонённую карточку при ошибке другого сохранения', async () => {
    setSession({ accessToken: 'a', refreshToken: 'r' });
    const first = deferred();
    const second = deferred();
    const { client, wrapper } = setup((url, init) => {
      if (init?.method === 'PUT')
        return url.pathname.endsWith('/2') ? first.promise : second.promise;
      return json({ code: 'unavailable', status: 503 }, 503);
    });
    client.setQueryData(favoritesQueryKey('ru'), { items: [card('1')] });
    const { result } = renderHook(
      () => ({ list: useFavorites('ru'), toggle: useToggleFavorite('ru') }),
      {
        wrapper,
      },
    );

    act(() => result.current.toggle.mutate({ card: card('2'), on: true }));
    await waitFor(() => expect(ids(client)).toEqual(['2', '1']));
    act(() => result.current.toggle.mutate({ card: card('3'), on: true }));
    await waitFor(() => expect(ids(client)).toEqual(['3', '2', '1']));

    first.resolve(json({ code: 'favorites_full', status: 409 }, 409));
    await waitFor(() => expect(client.isMutating()).toBe(1));
    second.resolve(json({ code: 'favorites_full', status: 409 }, 409));
    await waitFor(() => expect(result.current.toggle.isError).toBe(true));
    expect(ids(client)).toEqual(['1']);
    expect(result.current.list.data?.items).toEqual([card('1')]);
  });

  it('возвращает удалённую карточку на прежнее место при отказе сервера', async () => {
    setSession({ accessToken: 'a', refreshToken: 'r' });
    const answer = deferred();
    const { client, wrapper } = setup((_url, init) =>
      init?.method === 'DELETE' ? answer.promise : json({ code: 'unavailable', status: 503 }, 503),
    );
    const saved = { items: [card('1'), card('2'), card('3')] };
    client.setQueryData(favoritesQueryKey('ru'), saved);
    const { result } = renderHook(
      () => ({ list: useFavorites('ru'), toggle: useToggleFavorite('ru') }),
      {
        wrapper,
      },
    );

    act(() => result.current.toggle.mutate({ card: card('2'), on: false }));
    await waitFor(() => expect(ids(client)).toEqual(['1', '3']));
    answer.resolve(json({ code: 'unavailable', status: 503 }, 503));
    await waitFor(() => expect(result.current.toggle.isError).toBe(true));
    expect(result.current.list.data).toEqual(saved);
  });

  it('asks nothing for a guest', () => {
    const { fetch, wrapper } = setup(() => json({ items: [] }));

    const { result } = renderHook(() => useFavorites('ru'), { wrapper });

    expect(result.current.fetchStatus).toBe('idle');
    expect(fetch).not.toHaveBeenCalled();
  });

  it('puts a saved specialist first at once and rolls back when the server refuses', async () => {
    setSession({ accessToken: 'a', refreshToken: 'r' });
    const saved: FavoritesOut = { items: [card('1')] };
    const answer = deferred();
    const { client, wrapper } = setup((_url, init) =>
      init?.method === 'PUT' ? answer.promise : json(saved),
    );
    const { result } = renderHook(() => useBoth(), { wrapper });
    await waitFor(() => expect(result.current.list.data).toEqual(saved));

    act(() => result.current.toggle.mutate({ card: card('2'), on: true }));

    await waitFor(() => expect(ids(client)).toEqual(['2', '1']));
    answer.resolve(
      json({ type: 'x', title: 'x', status: 409, code: 'favorites_full', trace_id: null }, 409),
    );
    await waitFor(() => expect(result.current.toggle.isError).toBe(true));
    expect(ids(client)).toEqual(['1']);
  });

  it('drops a removed specialist at once', async () => {
    setSession({ accessToken: 'a', refreshToken: 'r' });
    let saved: FavoritesOut = { items: [card('1'), card('2')] };
    const answer = deferred();
    const { client, wrapper } = setup((_url, init) =>
      init?.method === 'DELETE' ? answer.promise : json(saved),
    );
    const { result } = renderHook(() => useBoth(), { wrapper });
    await waitFor(() => expect(result.current.list.data?.items).toHaveLength(2));

    act(() => result.current.toggle.mutate({ card: card('2'), on: false }));

    await waitFor(() => expect(ids(client)).toEqual(['1']));
    saved = { items: [card('1')] };
    answer.resolve(json(null, 204));
    await waitFor(() => expect(result.current.toggle.isSuccess).toBe(true));
    expect(ids(client)).toEqual(['1']);
  });
});
