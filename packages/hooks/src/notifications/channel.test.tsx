import type { NotificationSettingsOut, TelegramChannelOut } from '@sosed/api-client';
import {
  configureApiClient,
  getNotificationsGetNotificationSettingsQueryKey,
} from '@sosed/api-client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { describe, expect, it, vi } from 'vitest';

import type { WriteAccessClient } from './channel.ts';
import { WriteAccessDeclinedError, useBotChannel } from './channel.ts';

const SETTINGS: NotificationSettingsOut = {
  groups: [{ group: 'account', telegram: true, in_app: true, mandatory: true }],
  quiet_hours: { enabled: true, start: '22:00:00', end: '08:00:00', time_zone: 'Europe/Belgrade' },
  digest_hour: 9,
  telegram: null,
};
const CHANNEL: TelegramChannelOut = {
  writable: true,
  granted_via: 'mini_app',
  granted_at: '2026-10-13T10:00:00Z',
};
const KEY = getNotificationsGetNotificationSettingsQueryKey();

/** Сервер с памятью: разрешение видно и в настройках, как у backend. GET ждёт `release`, если
 *  тест хочет ответить им позже разрешения. */
function setup({ allowed = true, holdGet = false } = {}) {
  let telegram: TelegramChannelOut | null = null;
  const releases: (() => void)[] = [];
  const posts: string[] = [];
  const fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    if (init?.method === 'POST') {
      posts.push(String(input));
      telegram = CHANNEL;
      return Response.json(CHANNEL);
    }
    if (holdGet) await new Promise<void>((resolve) => releases.push(resolve));
    return Response.json({ ...SETTINGS, telegram } satisfies NotificationSettingsOut);
  });
  configureApiClient({ fetch, locale: () => 'ru' });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  const telegramClient: WriteAccessClient = {
    capabilities: { requestWriteAccess: true },
    requestWriteAccess: vi.fn(async () => allowed),
  };
  const cached = () => client.getQueryData<NotificationSettingsOut>(KEY);
  const release = async () => {
    await waitFor(() => expect(releases.length).toBeGreaterThan(0));
    await act(async () => releases.shift()?.());
  };
  return { client, wrapper, telegramClient, posts, cached, release };
}

describe('useBotChannel', () => {
  it('reads the channel from the settings and asks the client, then the server', async () => {
    const { wrapper, telegramClient, posts, cached } = setup();
    const { result } = renderHook(() => useBotChannel(telegramClient), { wrapper });
    expect(result.current.writable).toBeNull();
    await waitFor(() => expect(result.current.writable).toBe(false));
    expect(result.current.canAsk).toBe(true);

    await act(async () => result.current.allow.mutate());

    await waitFor(() => expect(result.current.allow.isSuccess).toBe(true));
    expect(telegramClient.requestWriteAccess).toHaveBeenCalledTimes(1);
    expect(posts).toEqual([expect.stringContaining('/me/telegram/write-access')]);
    expect(cached()?.telegram).toEqual(CHANNEL);
    expect(result.current.writable).toBe(true);
  });

  it('sends nothing when the person declines', async () => {
    const { wrapper, telegramClient, posts, cached } = setup({ allowed: false });
    const { result } = renderHook(() => useBotChannel(telegramClient), { wrapper });
    await waitFor(() => expect(result.current.writable).toBe(false));

    await act(async () => result.current.allow.mutate());

    await waitFor(() => expect(result.current.allow.isError).toBe(true));
    expect(result.current.allow.error).toBeInstanceOf(WriteAccessDeclinedError);
    expect(posts).toEqual([]);
    expect(cached()?.telegram).toBeNull();
    expect(result.current.writable).toBe(false);
  });

  it('keeps the channel when a GET started before the permission answers later', async () => {
    const { wrapper, telegramClient, cached, release } = setup({ holdGet: true });
    const { result } = renderHook(() => useBotChannel(telegramClient), { wrapper });
    // настройки ещё в пути — разрешение дано с другого экрана
    await act(async () => result.current.allow.mutate());
    await waitFor(() => expect(result.current.allow.isSuccess).toBe(true));

    // первый GET отменён: его «канала нет» ничего не затирает; перечитывание знает о канале
    await release();
    await release();
    await waitFor(() => expect(cached()?.telegram).toEqual(CHANNEL));
    expect(result.current.writable).toBe(true);
  });

  it('does not read the settings and cannot ask while disabled or unsupported', async () => {
    const { wrapper, client, telegramClient } = setup();
    const muted: WriteAccessClient = {
      ...telegramClient,
      capabilities: { requestWriteAccess: false },
    };
    const { result } = renderHook(() => useBotChannel(muted, { enabled: false }), { wrapper });
    await act(async () => undefined);
    expect(result.current.writable).toBeNull();
    expect(result.current.canAsk).toBe(false);
    expect(client.getQueryState(KEY)?.fetchStatus ?? 'idle').toBe('idle');
  });
});
