import { ApiError, configureApiClient, getSession, setSession } from '@sosed/api-client';
import type { Platform } from '@sosed/platform';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { contentSecurityPolicy } from './csp.ts';
import { shouldRetry } from './query.ts';
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
});
