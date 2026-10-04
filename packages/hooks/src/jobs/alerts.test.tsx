import type { JobAlertOut, JobAlertsOut } from '@sosed/api-client';
import { configureApiClient } from '@sosed/api-client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook } from '@testing-library/react';
import type { ReactNode } from 'react';
import { describe, expect, it, vi } from 'vitest';

import {
  alertsQueryKey,
  receives,
  useCreateAlert,
  useDeleteAlert,
  useJobAlerts,
  useUpdateAlert,
} from './alerts.ts';

const alert = (id: string, fields: Partial<JobAlertOut> = {}): JobAlertOut => ({
  id,
  criteria: {
    category_ids: [1],
    city_id: 1,
    district_ids: [],
    center: null,
    radius_km: null,
    min_budget: null,
    urgencies: [],
    languages: [],
  },
  delivery: 'instant',
  is_active: true,
  paused_until: null,
  week_count: 3,
  created_at: '2026-10-02T10:00:00Z',
  ...fields,
});

const json = (body: unknown, status = 200) =>
  new Response(status === 204 ? null : JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });

/** Список подписок на экране, его перечитывание висит: видно, что мутация его не ждёт. */
function setup(items: JobAlertOut[], answer: () => Response | Promise<Response>) {
  const fetch = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) =>
    (init?.method ?? 'GET') === 'GET' ? new Promise<Response>(() => undefined) : answer(),
  );
  configureApiClient({ fetch, locale: () => 'ru' });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  client.setQueryData<JobAlertsOut>(alertsQueryKey(), { items, limit: 10 });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  const listed = () => client.getQueryData<JobAlertsOut>(alertsQueryKey())?.items;
  return { wrapper, listed, fetch };
}

describe('job alerts', () => {
  it('puts the created alert at the end of the list from the response', async () => {
    const created = alert('a2', { week_count: 8 });
    const { wrapper, listed, fetch } = setup([alert('a1')], () => json(created, 201));
    const { result } = renderHook(() => [useJobAlerts(), useCreateAlert()] as const, { wrapper });

    await act(async () => {
      await result.current[1].mutateAsync({
        key: 'k1',
        body: { criteria: created.criteria, delivery: 'instant' },
      });
    });

    expect(listed()?.map((item) => [item.id, item.week_count])).toEqual([
      ['a1', 3],
      ['a2', 8],
    ]);
    const [, init] = fetch.mock.calls.find(([, call]) => call?.method === 'POST') ?? [];
    expect(new Headers(init?.headers).get('Idempotency-Key')).toBe('k1');
  });

  it('turns an alert off at once and back when the server refuses', async () => {
    let refuse!: (response: Response) => void;
    const { wrapper, listed } = setup(
      [alert('a1', { paused_until: '2026-10-09T10:00:00Z' })],
      () => new Promise<Response>((resolve) => (refuse = resolve)),
    );
    const { result } = renderHook(() => [useJobAlerts(), useUpdateAlert()] as const, { wrapper });

    let done!: Promise<unknown>;
    act(() => {
      done = result.current[1]
        .mutateAsync({ alertId: 'a1', body: { is_active: false } })
        .catch(() => undefined);
    });
    await vi.waitFor(() => expect(listed()?.[0]?.is_active).toBe(false));
    refuse(json({ code: 'internal_error' }, 500));
    await act(async () => {
      await done;
    });

    expect(listed()?.[0]).toEqual(alert('a1', { paused_until: '2026-10-09T10:00:00Z' }));
  });

  it('removes the deleted alert', async () => {
    const { wrapper, listed } = setup([alert('a1'), alert('a2')], () => json(null, 204));
    const { result } = renderHook(() => [useJobAlerts(), useDeleteAlert()] as const, { wrapper });

    await act(async () => {
      await result.current[1].mutateAsync('a1');
    });

    expect(listed()?.map((item) => item.id)).toEqual(['a2']);
  });

  it('a paused alert does not send until the pause ends', () => {
    const now = new Date('2026-10-03T10:00:00Z');
    expect(receives(alert('a1'), now)).toBe(true);
    expect(receives(alert('a1', { paused_until: '2026-10-04T00:00:00Z' }), now)).toBe(false);
    expect(receives(alert('a1', { paused_until: '2026-10-03T09:00:00Z' }), now)).toBe(true);
    expect(receives(alert('a1', { is_active: false }), now)).toBe(false);
  });
});
