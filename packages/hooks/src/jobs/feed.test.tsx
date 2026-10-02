import type { JobCardOut, JobsPageOut } from '@sosed/api-client';
import { configureApiClient, setSession } from '@sosed/api-client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { FeedPages } from './feed.ts';
import { useJobsCount } from './count.ts';
import { feedQueryKey, jobCards, useHideJob, useJobsFeed } from './feed.ts';

const card = (id: string): JobCardOut => ({
  id,
  title: `Заявка ${id}`,
  description: '',
  category_id: 101,
  urgency: 'today',
  preferred_from: null,
  preferred_to: null,
  budget_type: 'negotiable',
  budget_min: null,
  budget_max: null,
  budget_unit: 'work',
  district_id: null,
  distance_m: null,
  photos: [],
  photos_count: 0,
  responses_count: 0,
  max_responses: 5,
  published_at: '2026-10-02T10:00:00Z',
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

const QUERY = { city_id: 1, urgency: ['asap' as const, 'today' as const] };

describe('jobs feed', () => {
  it('asks nothing until the city is known', () => {
    const { fetch, wrapper } = setup(() => json({ items: [], next_cursor: null }));

    const { result } = renderHook(() => useJobsFeed(null), { wrapper });

    expect(result.current.fetchStatus).toBe('idle');
    expect(fetch).not.toHaveBeenCalled();
  });

  it('pages by the cursor with the filters of the query', async () => {
    const pages: Record<string, JobsPageOut> = {
      first: { items: [card('1'), card('2')], next_cursor: 'c2' },
      c2: { items: [card('3')], next_cursor: null },
    };
    const { fetch, wrapper } = setup((url) =>
      json(pages[url.searchParams.get('cursor') ?? 'first']),
    );

    const { result } = renderHook(() => useJobsFeed(QUERY), { wrapper });
    await waitFor(() => expect(result.current.data).toBeDefined());
    await act(async () => {
      await result.current.fetchNextPage();
    });

    await waitFor(() =>
      expect(jobCards(result.current.data).map((job) => job.id)).toEqual(['1', '2', '3']),
    );
    expect(result.current.hasNextPage).toBe(false);
    const [first, second] = fetch.mock.calls.map(([input]) => new URL(String(input), 'http://x'));
    expect(first?.searchParams.get('limit')).toBe('20');
    expect(first?.searchParams.getAll('urgency')).toEqual(['asap', 'today']);
    expect(first?.searchParams.has('cursor')).toBe(false);
    expect(second?.searchParams.get('cursor')).toBe('c2');
  });

  it('counts new jobs of the last hours', async () => {
    const { fetch, wrapper } = setup(() => json({ count: 6 }));

    const { result } = renderHook(() => useJobsCount({ city_id: 1 }, 24), { wrapper });

    await waitFor(() => expect(result.current.data).toEqual({ count: 6 }));
    const url = new URL(String(fetch.mock.calls[0]?.[0]), 'http://x');
    expect(url.pathname).toBe('/api/v1/jobs/count');
    expect(url.searchParams.get('new_hours')).toBe('24');
  });

  it('takes a hidden job out of every loaded feed at once, then rereads them', async () => {
    setSession({ accessToken: 'a', refreshToken: 'r' });
    const { fetch, client, wrapper } = setup((_url, init) =>
      init?.method === 'POST' ? json(null, 204) : json({ items: [card('2')], next_cursor: null }),
    );
    const loaded: FeedPages = {
      pages: [{ items: [card('1'), card('2')], next_cursor: null }],
      pageParams: [null],
    };
    client.setQueryData(feedQueryKey({ city_id: 1 }), loaded);
    client.setQueryData(feedQueryKey(QUERY), loaded);

    const { result } = renderHook(() => useHideJob(), { wrapper });
    act(() => result.current.mutate('1'));

    for (const query of [{ city_id: 1 }, QUERY]) {
      await waitFor(() =>
        expect(
          jobCards(client.getQueryData<FeedPages>(feedQueryKey(query))).map((job) => job.id),
        ).toEqual(['2']),
      );
    }
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    const hide = fetch.mock.calls.find(([, init]) => init?.method === 'POST');
    expect(new URL(String(hide?.[0]), 'http://x').pathname).toBe('/api/v1/jobs/1/hide');
  });
});
