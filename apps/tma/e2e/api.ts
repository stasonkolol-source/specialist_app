// API для e2e: ответы из фикстур SPEC §4 через page.route — тот же контракт, что MSW в Vitest,
// без service worker. Неописанный запрос к /api — ошибка теста.
import type { Page } from '@playwright/test';

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

export async function mockApi(page: Page, unexpected: string[]): Promise<void> {
  await page.route('**/api/v1/**', (route) => {
    const url = new URL(route.request().url());
    const key = `${route.request().method()} ${url.pathname}`;
    switch (key) {
      case 'GET /api/v1/client-config':
        return route.fulfill(json(CLIENT_CONFIG));
      case 'GET /api/v1/me':
        return route.fulfill(json(ME));
      // mock-платформа шлёт синтетический initData: backend его отверг бы
      case 'POST /api/v1/auth/telegram':
        return route.fulfill(json(INVALID_INIT_DATA, 401));
      default:
        unexpected.push(key);
        return route.fulfill(json({ ...INVALID_INIT_DATA, status: 404, code: 'not_found' }, 404));
    }
  });
}
