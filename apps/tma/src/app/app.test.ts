import {
  ApiError,
  MaintenanceError,
  configureApiClient,
  getSession,
  setSession,
} from '@sosed/api-client';
import type { Platform } from '@sosed/platform';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { contentSecurityPolicy } from './csp.ts';
import { createQueryClient, shouldRetry } from './query.ts';
import { createAuth } from './session.ts';

describe('CSP', () => {
  it('is strict in production and lets Telegram Web frame the app', () => {
    const csp = contentSecurityPolicy({ dev: false, mediaOrigins: ['https://media.example'] });
    expect(csp).toContain("script-src 'self';");
    expect(csp).toContain("style-src 'self';");
    expect(csp).toContain("connect-src 'self';");
    expect(csp).toContain("img-src 'self' data: blob: https://media.example");
    expect(csp).toContain('frame-ancestors https://web.telegram.org');
    expect(csp).not.toContain('unsafe');
  });

  it('allows Vite inline preamble and HMR socket in development', () => {
    const csp = contentSecurityPolicy({ dev: true, mediaOrigins: [] });
    expect(csp).toContain("script-src 'self' 'unsafe-inline'");
    expect(csp).toContain("connect-src 'self' ws: wss:");
  });

  it('lets the app upload to and preview from the storage S3 API', () => {
    const csp = contentSecurityPolicy({
      dev: false,
      mediaOrigins: [],
      storageOrigins: ['https://s3.example'],
    });
    expect(csp).toContain("connect-src 'self' https://s3.example;");
    expect(csp).toContain("img-src 'self' data: blob: https://s3.example;");
    expect(csp).toContain("media-src 'self' blob: https://s3.example;");
  });
});

describe('query retries', () => {
  const problem = (status: number) =>
    new ApiError({ type: 'x', title: 't', status, code: 'c', trace_id: null });

  it('does not retry client errors and retries others twice', () => {
    expect(shouldRetry(0, problem(404))).toBe(false);
    expect(shouldRetry(0, problem(503))).toBe(true);
    expect(shouldRetry(1, new TypeError('offline'))).toBe(true);
    expect(shouldRetry(2, problem(503))).toBe(false);
  });

  it('does not retry maintenance: the answer will not change in a second', () => {
    const maintenance = new MaintenanceError(
      { type: 'x', title: 't', status: 503, code: 'maintenance', trace_id: null },
      120,
    );
    expect(shouldRetry(0, maintenance)).toBe(false);
  });

  it('keeps unused data for 30 minutes and /me fresh for 5', () => {
    const client = createQueryClient();
    expect(client.getDefaultOptions().queries?.gcTime).toBe(30 * 60_000);
    // ленты и свои заявки — 30 с: их меняют чужие действия
    const staleOf = (queryKey: readonly unknown[]) =>
      client.defaultQueryOptions({ queryKey }).staleTime;
    expect(staleOf(['/api/v1/jobs', { city_id: 1 }])).toBe(30_000);
    expect(staleOf(['/api/v1/me/jobs'])).toBe(30_000);
    // /me — всю сессию: по нему решает охрана маршрутов
    expect(client.defaultQueryOptions({ queryKey: ['/api/v1/me'] })).toMatchObject({
      gcTime: Infinity,
      staleTime: 5 * 60_000,
    });
  });

  it('fails offline requests instead of pausing them: the screen shows S49a', () => {
    const defaults = createQueryClient().getDefaultOptions();
    expect(defaults.queries?.networkMode).toBe('always');
    expect(defaults.mutations?.networkMode).toBe('always');
  });
});

describe('sign in by initData', () => {
  afterEach(() => setSession(null));

  const platformWith = (rawInitData: string | null) =>
    ({ launch: { rawInitData } }) as unknown as Platform;

  const tokens = {
    token_type: 'Bearer',
    access_token: 'a1',
    access_expires_at: '2026-09-27T10:27:00Z',
    refresh_token: 'r1',
    refresh_expires_at: '2026-10-04T10:12:00Z',
    is_new: true,
    user: { id: 'u1', ui_locale: 'sr-Cyrl' },
  };

  it('exchanges initData once for parallel callers and keeps tokens in memory', async () => {
    const fetch = vi.fn(async () => new Response(JSON.stringify(tokens), { status: 200 }));
    configureApiClient({ fetch });
    const onSignedIn = vi.fn();
    const auth = createAuth(platformWith('user=1&hash=abc'), onSignedIn);

    await expect(Promise.all([auth.signIn(), auth.signIn()])).resolves.toEqual([true, true]);

    expect(fetch).toHaveBeenCalledOnce();
    // пользователь из ответа — для языка, сохранённого на сервере
    expect(onSignedIn).toHaveBeenCalledExactlyOnceWith(tokens.user);
    const [url, init] = fetch.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe('/api/v1/auth/telegram');
    expect(new Headers(init.headers).get('Authorization')).toBe('tma user=1&hash=abc');
    expect(getSession()).toEqual({ accessToken: 'a1', refreshToken: 'r1' });
  });

  it('does nothing outside Telegram and reports failed exchange', async () => {
    const fetch = vi.fn(
      async () =>
        new Response(JSON.stringify({ status: 401, code: 'init_data_expired' }), { status: 401 }),
    );
    configureApiClient({ fetch });
    const onSignedIn = vi.fn();

    await expect(createAuth(platformWith(null), onSignedIn).signIn()).resolves.toBe(false);
    expect(fetch).not.toHaveBeenCalled();
    await expect(createAuth(platformWith('stale'), onSignedIn).signIn()).resolves.toBe(false);
    expect(getSession()).toBeNull();
    expect(onSignedIn).not.toHaveBeenCalled();
  });

  it('launch: one exchange for S01 and main.tsx, the user and «new» come with it', async () => {
    const fetch = vi.fn(async () => new Response(JSON.stringify(tokens), { status: 200 }));
    configureApiClient({ fetch });
    const auth = createAuth(platformWith('user=1&hash=abc'));

    const [first, second] = await Promise.all([auth.launch(), auth.launch()]);

    expect(first).toEqual({ kind: 'signed-in', user: tokens.user, isNew: true });
    expect(second).toBe(first);
    await expect(auth.launch()).resolves.toBe(first);
    expect(fetch).toHaveBeenCalledOnce();
  });

  it('launch: a guest without Telegram or with refused initData, a failure otherwise', async () => {
    const refused = vi.fn(
      async () =>
        new Response(JSON.stringify({ status: 401, code: 'invalid_init_data' }), { status: 401 }),
    );
    configureApiClient({ fetch: refused });
    await expect(createAuth(platformWith(null)).launch()).resolves.toEqual({ kind: 'guest' });
    await expect(createAuth(platformWith('stale')).launch()).resolves.toEqual({ kind: 'guest' });

    const offline = vi.fn(async () => {
      throw new TypeError('Failed to fetch');
    });
    configureApiClient({ fetch: offline });
    const onRefused = vi.fn();
    const result = await createAuth(platformWith('user=1'), undefined, onRefused).launch();
    expect(result.kind).toBe('failed');
    expect(onRefused).toHaveBeenCalledOnce();
  });

  it('launch: after a failure the next call signs in again («Повторить»)', async () => {
    let online = false;
    const fetch = vi.fn(async () => {
      if (!online) throw new TypeError('Failed to fetch');
      return new Response(JSON.stringify(tokens), { status: 200 });
    });
    configureApiClient({ fetch });
    const auth = createAuth(platformWith('user=1'));

    expect((await auth.launch()).kind).toBe('failed');
    online = true;
    expect((await auth.launch()).kind).toBe('signed-in');
    expect((await auth.launch()).kind).toBe('signed-in');
    expect(fetch).toHaveBeenCalledTimes(2);
  });
});
