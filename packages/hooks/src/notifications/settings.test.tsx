import type { NotificationSettingsIn, NotificationSettingsOut } from '@sosed/api-client';
import {
  configureApiClient,
  getNotificationsGetNotificationSettingsQueryKey,
} from '@sosed/api-client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { describe, expect, it, vi } from 'vitest';

import { applyChange, settingsIn, useUpdateNotificationSettings } from './settings.ts';

const SETTINGS: NotificationSettingsOut = {
  groups: [
    { group: 'messages', telegram: true, in_app: true, mandatory: false },
    { group: 'marketing', telegram: false, in_app: false, mandatory: false },
    { group: 'account', telegram: true, in_app: true, mandatory: true },
  ],
  quiet_hours: { enabled: true, start: '22:00:00', end: '08:00:00', time_zone: 'Europe/Belgrade' },
  digest_hour: 9,
  telegram: null,
};

const KEY = getNotificationsGetNotificationSettingsQueryKey();

/** Сервер отвечает на PUT тем, что получил; ответ ждёт `release`, пока тест не отпустит. */
function setup({ fail = false } = {}) {
  const bodies: NotificationSettingsIn[] = [];
  const releases: (() => void)[] = [];
  const fetch = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
    // перечитывание после ошибки — настройки как были
    if (init?.method !== 'PUT') return Response.json(SETTINGS);
    const body = JSON.parse(String(init.body)) as NotificationSettingsIn;
    bodies.push(body);
    await new Promise<void>((resolve) => releases.push(resolve));
    if (fail) {
      return new Response(JSON.stringify({ status: 500, code: 'internal_error' }), {
        status: 500,
        headers: { 'Content-Type': 'application/problem+json' },
      });
    }
    const sent = (group: string) => body.groups.find((row) => row.group === group);
    return Response.json({
      ...SETTINGS,
      groups: SETTINGS.groups.map((row) => ({ ...row, ...sent(row.group) })),
      quiet_hours: { ...SETTINGS.quiet_hours, enabled: body.quiet_hours.enabled },
    } satisfies NotificationSettingsOut);
  });
  configureApiClient({ fetch, locale: () => 'ru' });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  client.setQueryData(KEY, SETTINGS);
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  const cached = () => client.getQueryData<NotificationSettingsOut>(KEY);
  const release = async () => {
    await waitFor(() => expect(releases.length).toBeGreaterThan(0));
    await act(async () => releases.shift()?.());
  };
  return { fetch, client, wrapper, bodies, cached, release };
}

describe('applyChange and settingsIn', () => {
  it('changes one channel of one group and never the service group', () => {
    const next = applyChange(SETTINGS, { group: 'messages', channel: 'telegram', on: false });
    expect(next.groups[0]).toEqual({
      group: 'messages',
      telegram: false,
      in_app: true,
      mandatory: false,
    });
    expect(applyChange(SETTINGS, { group: 'account', channel: 'telegram', on: false })).toEqual(
      SETTINGS,
    );
    expect(applyChange(SETTINGS, { quiet: false }).quiet_hours.enabled).toBe(false);
  });

  it('sends everything visible except the service group', () => {
    expect(settingsIn(SETTINGS)).toEqual({
      groups: [
        { group: 'messages', telegram: true, in_app: true },
        { group: 'marketing', telegram: false, in_app: false },
      ],
      quiet_hours: { enabled: true, start: '22:00:00', end: '08:00:00' },
      digest_hour: 9,
    });
  });
});

describe('useUpdateNotificationSettings', () => {
  it('shows the choice at once and keeps the server answer', async () => {
    const { wrapper, cached, release, bodies } = setup();
    const { result } = renderHook(() => useUpdateNotificationSettings(), { wrapper });

    act(() => result.current.mutate({ quiet: false }));

    await waitFor(() => expect(cached()?.quiet_hours.enabled).toBe(false));
    await release();
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(bodies.map((body) => body.quiet_hours.enabled)).toEqual([false]);
    expect(cached()?.quiet_hours.enabled).toBe(false);
  });

  it('sends taps one by one, each with the earlier ones, and an early answer does not undo a later tap', async () => {
    const { wrapper, cached, release, bodies } = setup();
    const { result } = renderHook(() => useUpdateNotificationSettings(), { wrapper });

    act(() => result.current.mutate({ group: 'messages', channel: 'telegram', on: false }));
    act(() => result.current.mutate({ group: 'marketing', channel: 'in_app', on: true }));
    await waitFor(() => expect(bodies).toHaveLength(1));

    await release();
    // первый ответ ещё без новостей: экран их не теряет
    expect(cached()?.groups[1]?.in_app).toBe(true);
    await waitFor(() => expect(bodies).toHaveLength(2));
    expect(bodies[1]?.groups).toEqual([
      { group: 'messages', telegram: false, in_app: true },
      { group: 'marketing', telegram: false, in_app: true },
    ]);
    await release();
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(cached()?.groups.slice(0, 2)).toEqual([
      { group: 'messages', telegram: false, in_app: true, mandatory: false },
      { group: 'marketing', telegram: false, in_app: true, mandatory: false },
    ]);
  });

  it('returns only its own mark when the server fails', async () => {
    const { wrapper, cached, release } = setup({ fail: true });
    const { result } = renderHook(() => useUpdateNotificationSettings(), { wrapper });

    act(() => result.current.mutate({ group: 'messages', channel: 'in_app', on: false }));
    await waitFor(() => expect(cached()?.groups[0]?.in_app).toBe(false));
    await release();

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(cached()?.groups[0]?.in_app).toBe(true);
  });
});
