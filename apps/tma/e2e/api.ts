// API для e2e: ответы из фикстур SPEC §4 через page.route — тот же контракт, что MSW в Vitest,
// без service worker. Неописанный запрос к /api — ошибка теста.
import type {
  ClientConfigOut,
  MeOut,
  NotificationPageOut,
  NotificationSettingsOut,
} from '@sosed/api-client';
import type { Page, Request, Route } from '@playwright/test';

import {
  CLIENT_CONFIG,
  ME,
  NOTIFICATION_SETTINGS,
  WRITE_ACCESS,
  accepted,
  citiesFor,
  notificationsFor,
} from '../src/testing/fixtures.ts';

export const json = (body: unknown, status = 200) => ({
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

/** Ответ RFC 9457, как у backend: `code` и поля конкретной ошибки. */
export const problem = (status: number, code: string, extra: Record<string, unknown> = {}) =>
  json({ type: 'about:blank', title: code, status, code, trace_id: 'e2e', ...extra }, status);

export interface MockApiOptions {
  /** true — POST /auth/telegram принимает initData mock-платформы, как backend в Telegram. */
  signedIn?: boolean;
  /** Пользователь /me и входа; по умолчанию ME из фикстур. */
  me?: MeOut;
  /** GET /client-config; по умолчанию CLIENT_CONFIG из фикстур. */
  config?: ClientConfigOut;
  /** GET /me/notifications; по умолчанию — лента фикстур на языке запроса. */
  notifications?: NotificationPageOut;
  /** GET /me/notification-settings; по умолчанию бот писать не может (баннер S42). */
  notificationSettings?: NotificationSettingsOut;
  /** Свои ответы по ключу «METHOD /api/v1/…»: проверяются раньше стандартных. */
  handlers?: Record<string, (route: Route) => Promise<void>>;
  /** Что приложение прислало в PATCH /me, POST /me/consents, POST /me/telegram/write-access и
   *  POST /me/notifications/read. */
  sent?: SentRequests;
}

export interface SentRequests {
  patch: unknown[];
  consents: unknown[];
  writeAccess: number;
  read: unknown[];
}

export const sentRequests = (): SentRequests => ({
  patch: [],
  consents: [],
  writeAccess: 0,
  read: [],
});

const authorized = (request: Request) =>
  request.headers()['authorization'] === `Bearer ${TOKENS.access_token}`;

export async function mockApi(
  page: Page,
  unexpected: string[],
  {
    signedIn = false,
    me = ME,
    config = CLIENT_CONFIG,
    notifications,
    notificationSettings = NOTIFICATION_SETTINGS,
    handlers = {},
    sent = sentRequests(),
  }: MockApiOptions = {},
): Promise<void> {
  // пользователь с памятью, как на сервере: онбординг меняет его шаг за шагом
  let user = me;
  await page.route('**/api/v1/**', (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const key = `${request.method()} ${url.pathname}`;
    const handler = handlers[key];
    if (handler) return handler(route);
    switch (key) {
      case 'GET /api/v1/client-config':
        return route.fulfill(json(config));
      case 'GET /api/v1/cities':
        return route.fulfill(json(citiesFor(request.headers()['accept-language'] ?? null)));
      case 'GET /api/v1/me':
        return route.fulfill(authorized(request) ? json(user) : json(NOT_AUTHENTICATED, 401));
      case 'PATCH /api/v1/me': {
        if (!authorized(request)) return route.fulfill(json(NOT_AUTHENTICATED, 401));
        const body = request.postDataJSON() as Record<string, unknown>;
        sent.patch.push(body);
        const fields = Object.entries(body).filter(([, value]) => value != null);
        user = { ...user, ...Object.fromEntries(fields) };
        return route.fulfill(json(user));
      }
      case 'POST /api/v1/me/consents':
        if (!authorized(request)) return route.fulfill(json(NOT_AUTHENTICATED, 401));
        sent.consents.push(request.postDataJSON());
        user = accepted(user);
        return route.fulfill(json(user));
      case 'POST /api/v1/me/telegram/write-access':
        if (!authorized(request)) return route.fulfill(json(NOT_AUTHENTICATED, 401));
        sent.writeAccess += 1;
        return route.fulfill(json(WRITE_ACCESS));
      // S42 и счётчик непрочитанных на S31: тексты — на языке запроса, как у backend
      case 'GET /api/v1/me/notifications':
        if (!authorized(request)) return route.fulfill(json(NOT_AUTHENTICATED, 401));
        return route.fulfill(
          json(notifications ?? notificationsFor(request.headers()['accept-language'] ?? null)),
        );
      case 'POST /api/v1/me/notifications/read':
        if (!authorized(request)) return route.fulfill(json(NOT_AUTHENTICATED, 401));
        sent.read.push(request.postDataJSON());
        return route.fulfill(json({ unread_count: 0 }));
      case 'GET /api/v1/me/notification-settings':
        if (!authorized(request)) return route.fulfill(json(NOT_AUTHENTICATED, 401));
        return route.fulfill(json(notificationSettings));
      // по умолчанию backend отверг бы синтетический initData mock-платформы
      case 'POST /api/v1/auth/telegram':
        return route.fulfill(
          signedIn ? json({ ...TOKENS, is_new: false, user }) : json(INVALID_INIT_DATA, 401),
        );
      default:
        unexpected.push(key);
        return route.fulfill(json({ ...INVALID_INIT_DATA, status: 404, code: 'not_found' }, 404));
    }
  });
}
