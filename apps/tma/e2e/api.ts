// API для e2e: ответы из фикстур SPEC §4 через page.route — тот же контракт, что MSW в Vitest,
// без service worker. Неописанный запрос к /api — ошибка теста.
import type { Page, Request } from '@playwright/test';

import { CLIENT_CONFIG, ME } from '../src/testing/fixtures.ts';

const json = (body: unknown, status = 200) => ({
  status,
  contentType: status >= 400 ? 'application/problem+json' : 'application/json',
  body: JSON.stringify(body),
});

const INVALID_INIT_DATA = {
  type: 'about:blank',
  title: 'Unauthorized',
  status: 401,
  code: 'invalid_init_data',
  trace_id: 'e2e',
};

const NOT_AUTHENTICATED = { ...INVALID_INIT_DATA, code: 'not_authenticated' };

const TOKENS = {
  token_type: 'Bearer',
  access_token: 'e2e-access',
  access_expires_at: '2026-10-05T09:15:00Z',
  refresh_token: 'e2e-refresh',
  refresh_expires_at: '2026-10-12T09:00:00Z',
};

export interface MockApiOptions {
  /** true — POST /auth/telegram принимает initData mock-платформы, как backend в Telegram. */
  signedIn?: boolean;
}

const authorized = (request: Request) =>
  request.headers()['authorization'] === `Bearer ${TOKENS.access_token}`;

export async function mockApi(
  page: Page,
  unexpected: string[],
  { signedIn = false }: MockApiOptions = {},
): Promise<void> {
  await page.route('**/api/v1/**', (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const key = `${request.method()} ${url.pathname}`;
    switch (key) {
      case 'GET /api/v1/client-config':
        return route.fulfill(json(CLIENT_CONFIG));
      case 'GET /api/v1/me':
        return route.fulfill(authorized(request) ? json(ME) : json(NOT_AUTHENTICATED, 401));
      case 'PATCH /api/v1/me':
        return route.fulfill(
          authorized(request)
            ? json({ ...ME, ...(request.postDataJSON() as object) })
            : json(NOT_AUTHENTICATED, 401),
        );
      // по умолчанию backend отверг бы синтетический initData mock-платформы
      case 'POST /api/v1/auth/telegram':
        return route.fulfill(
          signedIn ? json({ ...TOKENS, is_new: false, user: ME }) : json(INVALID_INIT_DATA, 401),
        );
      default:
        unexpected.push(key);
        return route.fulfill(json({ ...INVALID_INIT_DATA, status: 404, code: 'not_found' }, 404));
    }
  });
}
