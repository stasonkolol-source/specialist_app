import type { JobCardOut, SavedJobsOut } from '@sosed/api-client';
import { configureApiClient, setSession } from '@sosed/api-client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { savedJobIds, savedJobsQueryKey, useSavedJobs, useToggleSavedJob } from './saved.ts';

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

const ids = (client: QueryClient) => [
  ...savedJobIds(client.getQueryData<SavedJobsOut>(savedJobsQueryKey())),
];

/** Ответ сервера, который приходит, когда тест скажет: видно состояние до него. */
function deferred() {
  let resolve!: (response: Response) => void;
  const promise = new Promise<Response>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

describe('saved jobs', () => {
  it('asks nothing for a guest', () => {
    const { fetch, wrapper } = setup(() => json({ items: [] }));

    const { result } = renderHook(() => useSavedJobs(), { wrapper });

    expect(result.current.fetchStatus).toBe('idle');
    expect(fetch).not.toHaveBeenCalled();
  });

  it('puts a saved job first at once and rolls back when the server refuses', async () => {
    setSession({ accessToken: 'a', refreshToken: 'r' });
    const answer = deferred();
    const { client, wrapper } = setup((_url, init) =>
      init?.method === 'PUT' ? answer.promise : json({ items: [card('1')] }),
    );
    const { result } = renderHook(() => ({ list: useSavedJobs(), toggle: useToggleSavedJob() }), {
      wrapper,
    });
    await waitFor(() => expect(result.current.list.data).toBeDefined());

    act(() => result.current.toggle.mutate({ card: card('2'), on: true }));

    await waitFor(() => expect(ids(client)).toEqual(['2', '1']));
    answer.resolve(json({ code: 'saved_jobs_full', limit: 100, status: 409 }, 409));
    await waitFor(() => expect(result.current.toggle.isError).toBe(true));
    expect(ids(client)).toEqual(['1']);
  });

  it('takes a job out at once and rereads the list', async () => {
    setSession({ accessToken: 'a', refreshToken: 'r' });
    let saved = [card('1'), card('2')];
    const { fetch, client, wrapper } = setup((url, init) => {
      if (init?.method === 'DELETE') {
        saved = saved.filter((item) => !url.pathname.endsWith(item.id));
        return json(null, 204);
      }
      return json({ items: saved });
    });
    const { result } = renderHook(() => ({ list: useSavedJobs(), toggle: useToggleSavedJob() }), {
      wrapper,
    });
    await waitFor(() => expect(result.current.list.data).toBeDefined());

    act(() => result.current.toggle.mutate({ card: card('1'), on: false }));

    await waitFor(() => expect(ids(client)).toEqual(['2']));
    await waitFor(() => expect(result.current.toggle.isSuccess).toBe(true));
    const remove = fetch.mock.calls.find(([, init]) => init?.method === 'DELETE');
    expect(new URL(String(remove?.[0]), 'http://x').pathname).toBe('/api/v1/me/favorites/job/1');
  });
});
