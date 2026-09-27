import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  ApiError,
  NetworkError,
  RateLimitedError,
  RestrictedError,
  UpgradeRequiredError,
} from './errors.ts';
import {
  identityGetMe,
  identityRefreshSession,
  identityUpdateMe,
} from './generated/endpoints/index.ts';
import { apiFetch, configureApiClient, getSession, resetApiClient, setSession } from './mutator.ts';

type Handler = (url: string, init: RequestInit) => Response | Promise<Response>;

const json = (status: number, body: unknown, headers: Record<string, string> = {}): Response =>
  new Response(JSON.stringify(body), {
    status,
    headers: {
      'Content-Type': status >= 400 ? 'application/problem+json' : 'application/json',
      ...headers,
    },
  });

const problem = (status: number, code: string, extra: Record<string, unknown> = {}) =>
  json(status, { type: 'x', title: 't', status, code, trace_id: 'trace-1', ...extra });

const ME = {
  id: '01a0e259-a46c-75cb-8a6f-c52d857316af',
  display_name: 'Ана',
  ui_locale: 'sr-Latn',
  trust_level: 0,
  phone_verified: false,
  created_at: '2026-09-27T10:12:00Z',
};

const TOKENS = {
  token_type: 'Bearer',
  access_token: 'access-2',
  access_expires_at: '2026-09-27T10:27:00Z',
  refresh_token: 'refresh-2',
  refresh_expires_at: '2026-10-04T10:12:00Z',
};

/** fetch-заглушка: записывает запросы и отвечает обработчиком по очереди вызовов. */
const stubFetch = (handler: Handler) => {
  const calls: { url: string; init: RequestInit; headers: Headers }[] = [];
  const fetch = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = String(input);
    calls.push({ url, init, headers: new Headers(init.headers) });
    return handler(url, init);
  });
  return { fetch, calls };
};

const sleep = vi.fn(async () => undefined);

beforeEach(() => {
  resetApiClient();
  sleep.mockClear();
});

afterEach(() => {
  resetApiClient();
});

describe('headers and session', () => {
  it('sends locale, client, bearer from memory and no idempotency key for GET', async () => {
    const { fetch, calls } = stubFetch(() => json(200, ME));
    configureApiClient({ fetch, client: 'tma/1.3.0', locale: () => 'sr-Latn', baseUrl: '' });
    setSession({ accessToken: 'access-1', refreshToken: 'refresh-1' });

    await expect(identityGetMe()).resolves.toEqual(ME);

    const [call] = calls;
    expect(call?.url).toBe('/api/v1/me');
    expect(call?.headers.get('Accept-Language')).toBe('sr-Latn');
    expect(call?.headers.get('X-Client')).toBe('tma/1.3.0');
    expect(call?.headers.get('Authorization')).toBe('Bearer access-1');
    expect(call?.headers.has('Idempotency-Key')).toBe(false);
  });

  it('passes If-Match from the generated header parameter', async () => {
    const { fetch, calls } = stubFetch(() => json(200, ME));
    configureApiClient({ fetch });
    setSession({ accessToken: 'a', refreshToken: 'r' });

    await identityUpdateMe({ display_name: 'Ана' }, { 'If-Match': '"3"' });

    expect(calls[0]?.init.method).toBe('PATCH');
    expect(calls[0]?.headers.get('If-Match')).toBe('"3"');
    expect(calls[0]?.init.body).toBe(JSON.stringify({ display_name: 'Ана' }));
  });

  it('adds an idempotency key to POSTs unless the caller set one', async () => {
    const { fetch, calls } = stubFetch(() => json(201, {}));
    configureApiClient({ fetch });

    await apiFetch('/api/v1/jobs', { method: 'POST' });
    await apiFetch('/api/v1/jobs', { method: 'POST', headers: { 'Idempotency-Key': 'mine' } });

    expect(calls[0]?.headers.get('Idempotency-Key')).toMatch(/^[0-9a-f-]{36}$/);
    expect(calls[1]?.headers.get('Idempotency-Key')).toBe('mine');
  });

  it('does not send bearer or idempotency key to auth endpoints', async () => {
    const { fetch, calls } = stubFetch(() => json(200, TOKENS));
    configureApiClient({ fetch });
    setSession({ accessToken: 'a', refreshToken: 'r' });

    await identityRefreshSession({ refresh_token: 'r' });

    expect(calls[0]?.headers.has('Authorization')).toBe(false);
    expect(calls[0]?.headers.has('Idempotency-Key')).toBe(false);
  });

  it('returns undefined for 204', async () => {
    const { fetch } = stubFetch(() => new Response(null, { status: 204 }));
    configureApiClient({ fetch });
    await expect(apiFetch('/api/v1/auth/logout', { method: 'POST' })).resolves.toBeUndefined();
  });
});

describe('RFC 9457 errors', () => {
  it('parses problem into ApiError with code, field errors and trace id', async () => {
    const errors = [{ field: 'display_name', code: 'string_too_short', message: 'short' }];
    const { fetch } = stubFetch(() => problem(422, 'validation_error', { errors }));
    configureApiClient({ fetch });

    const error = await identityGetMe().catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({
      status: 422,
      code: 'validation_error',
      traceId: 'trace-1',
      errors,
    });
  });

  it('maps restricted, upgrade required and non-JSON bodies', async () => {
    const responses = [
      problem(403, 'restricted', { restriction: 'posting_blocked', until: '2026-10-05T09:00:00Z' }),
      problem(426, 'client_upgrade_required', { platform: 'tma', min_version: '1.2.0' }),
      new Response('<html>bad gateway</html>', { status: 502 }),
    ];
    const { fetch } = stubFetch(() => responses.shift() as Response);
    configureApiClient({ fetch });

    const restricted = await apiFetch('/api/v1/me').catch((e: unknown) => e);
    expect(restricted).toBeInstanceOf(RestrictedError);
    expect((restricted as RestrictedError).restriction).toBe('posting_blocked');
    expect((restricted as RestrictedError).until?.toISOString()).toBe('2026-10-05T09:00:00.000Z');

    const upgrade = await apiFetch('/api/v1/me').catch((e: unknown) => e);
    expect(upgrade).toBeInstanceOf(UpgradeRequiredError);
    expect((upgrade as UpgradeRequiredError).minVersion).toBe('1.2.0');

    const gateway = await apiFetch('/api/v1/me').catch((e: unknown) => e);
    expect(gateway).toMatchObject({ status: 502, code: 'http_502' });
  });

  it('wraps network failures', async () => {
    const fetch = vi.fn(async () => {
      throw new TypeError('Failed to fetch');
    });
    configureApiClient({ fetch });
    await expect(apiFetch('/api/v1/me')).rejects.toBeInstanceOf(NetworkError);
  });
});

describe('401: refresh and re-authentication', () => {
  it('refreshes an expired token once and retries with the new one', async () => {
    const { fetch, calls } = stubFetch((url, init) => {
      if (url === '/api/v1/auth/refresh') return json(200, TOKENS);
      const auth = new Headers(init.headers).get('Authorization');
      return auth === 'Bearer access-2' ? json(200, ME) : problem(401, 'token_expired');
    });
    configureApiClient({ fetch });
    setSession({ accessToken: 'access-1', refreshToken: 'refresh-1' });

    await expect(identityGetMe()).resolves.toEqual(ME);

    expect(calls.map((c) => c.url)).toEqual(['/api/v1/me', '/api/v1/auth/refresh', '/api/v1/me']);
    expect(calls[1]?.init.body).toBe(JSON.stringify({ refresh_token: 'refresh-1' }));
    expect(getSession()).toEqual({ accessToken: 'access-2', refreshToken: 'refresh-2' });
  });

  it('shares one refresh between parallel requests (single-flight)', async () => {
    let release: () => void = () => undefined;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const { fetch, calls } = stubFetch(async (url, init) => {
      if (url === '/api/v1/auth/refresh') {
        await gate;
        return json(200, TOKENS);
      }
      const auth = new Headers(init.headers).get('Authorization');
      return auth === 'Bearer access-2' ? json(200, ME) : problem(401, 'token_expired');
    });
    configureApiClient({ fetch });
    setSession({ accessToken: 'access-1', refreshToken: 'refresh-1' });

    const requests = [identityGetMe(), identityGetMe(), identityGetMe()];
    await vi.waitFor(() =>
      expect(calls.filter((c) => c.url === '/api/v1/auth/refresh')).toHaveLength(1),
    );
    release();

    await expect(Promise.all(requests)).resolves.toEqual([ME, ME, ME]);
    expect(calls.filter((c) => c.url === '/api/v1/auth/refresh')).toHaveLength(1);
  });

  it('calls onReauth when refresh fails and retries after a new login', async () => {
    const onReauth = vi.fn(async () => {
      setSession({ accessToken: 'access-3', refreshToken: 'refresh-3' });
      return true;
    });
    const { fetch, calls } = stubFetch((url, init) => {
      if (url === '/api/v1/auth/refresh') return problem(401, 'session_revoked');
      const auth = new Headers(init.headers).get('Authorization');
      return auth === 'Bearer access-3' ? json(200, ME) : problem(401, 'token_expired');
    });
    configureApiClient({ fetch, onReauth });
    setSession({ accessToken: 'access-1', refreshToken: 'refresh-1' });

    await expect(identityGetMe()).resolves.toEqual(ME);
    expect(onReauth).toHaveBeenCalledOnce();
    expect(calls.map((c) => c.url)).toEqual(['/api/v1/me', '/api/v1/auth/refresh', '/api/v1/me']);
  });

  it('skips refresh for revoked sessions and gives up if re-login fails', async () => {
    const onReauth = vi.fn(async () => false);
    const { fetch, calls } = stubFetch(() => problem(401, 'session_revoked'));
    configureApiClient({ fetch, onReauth });
    setSession({ accessToken: 'a', refreshToken: 'r' });

    const error = await identityGetMe().catch((e: unknown) => e);
    expect(error).toMatchObject({ status: 401, code: 'session_revoked' });
    expect(onReauth).toHaveBeenCalledOnce();
    expect(calls.map((c) => c.url)).toEqual(['/api/v1/me']);
  });

  it('retries at most once after re-authentication', async () => {
    const onReauth = vi.fn(async () => true);
    const { fetch, calls } = stubFetch(() => problem(401, 'invalid_token'));
    configureApiClient({ fetch, onReauth });

    await expect(identityGetMe()).rejects.toMatchObject({ code: 'invalid_token' });
    expect(onReauth).toHaveBeenCalledOnce();
    expect(calls).toHaveLength(2);
  });

  it('never refreshes or re-authenticates on the auth endpoints themselves', async () => {
    const onReauth = vi.fn(async () => true);
    const { fetch, calls } = stubFetch(() => problem(401, 'invalid_refresh_token'));
    configureApiClient({ fetch, onReauth });

    await expect(identityRefreshSession({ refresh_token: 'r' })).rejects.toMatchObject({
      code: 'invalid_refresh_token',
    });
    expect(onReauth).not.toHaveBeenCalled();
    expect(calls).toHaveLength(1);
  });
});

describe('429', () => {
  it('waits for a short Retry-After and retries once with the same idempotency key', async () => {
    const responses = [problem(429, 'rate_limited', {}), json(201, { id: 'x' })];
    const { fetch, calls } = stubFetch(() => {
      const next = responses.shift() as Response;
      return next.status === 429
        ? new Response(next.body, { status: 429, headers: { 'Retry-After': '2' } })
        : next;
    });
    configureApiClient({ fetch, sleep });

    await expect(apiFetch('/api/v1/jobs', { method: 'POST' })).resolves.toEqual({ id: 'x' });
    expect(sleep).toHaveBeenCalledWith(2000);
    expect(calls[0]?.headers.get('Idempotency-Key')).toBe(calls[1]?.headers.get('Idempotency-Key'));
  });

  it('gives up when Retry-After is longer than allowed', async () => {
    const { fetch } = stubFetch(
      () =>
        new Response(
          JSON.stringify({
            type: 'x',
            title: 't',
            status: 429,
            code: 'rate_limited',
            trace_id: null,
          }),
          {
            status: 429,
            headers: { 'Retry-After': '60' },
          },
        ),
    );
    configureApiClient({ fetch, sleep, maxRetryAfter: 10 });

    const error = await apiFetch('/api/v1/me').catch((e: unknown) => e);
    expect(error).toBeInstanceOf(RateLimitedError);
    expect((error as RateLimitedError).retryAfter).toBe(60);
    expect(sleep).not.toHaveBeenCalled();
  });
});
