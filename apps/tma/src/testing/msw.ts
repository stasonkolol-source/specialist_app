// MSW-обработчики orval с данными SPEC §4 (DEVELOPMENT_PLAN 0.21b): тесты Vitest видят API как
// настоящий backend. Для отдельного теста — server.use(<обработчик>) поверх этих.
import {
  getCatalogListCategoriesMockHandler,
  getGeoListCitiesMockHandler,
  getGeoListDistrictsMockHandler,
  getIdentityAcceptConsentsMockHandler,
  getIdentityAuthenticateTelegramMockHandler,
  getIdentityGetMeMockHandler,
  getIdentityLogoutMockHandler,
  getIdentityRefreshSessionMockHandler,
  getIdentityUpdateMeMockHandler,
  getNotificationsGetNotificationSettingsMockHandler,
  getNotificationsGrantTelegramWriteAccessMockHandler,
  getNotificationsListNotificationsMockHandler,
  getNotificationsMarkNotificationsReadMockHandler,
  getSystemGetClientConfigMockHandler,
} from '@sosed/api-client/mocks';
import type { MeOut, MeUpdateIn, TokensOut } from '@sosed/api-client';
import { HttpResponse, http } from 'msw';
import { setupServer } from 'msw/node';

import {
  CLIENT_CONFIG,
  ME,
  NOTIFICATION_SETTINGS,
  WRITE_ACCESS,
  accepted,
  categoriesFor,
  citiesFor,
  districtsFor,
  notificationsFor,
} from './fixtures.ts';
import { ProfileBackend } from './profileBackend.ts';

/** Origin API в тестах: fetch в Node не принимает относительные URL. */
export const API_ORIGIN = 'http://localhost';

export const TOKENS: TokensOut = {
  token_type: 'Bearer',
  access_token: 'test-access',
  access_expires_at: '2026-10-05T09:15:00Z',
  refresh_token: 'test-refresh',
  refresh_expires_at: '2026-10-12T09:00:00Z',
};

/** PATCH /me применяет присланные поля к `me`, как backend (и page.route в e2e/api.ts). */
export const patchMe = (me: MeOut) =>
  getIdentityUpdateMeMockHandler(async ({ request }) => {
    const body = (await request.json()) as MeUpdateIn;
    const fields = Object.fromEntries(Object.entries(body).filter(([, value]) => value != null));
    return { ...me, ...fields } as MeOut;
  });

/**
 * Кабинет исполнителя `/me/profile*` по фейку backend. По умолчанию — свежий на каждый запрос:
 * профиля нет. Тесты мастера S32a–c ставят свой — с памятью (server.use).
 */
export const profileHandlers = (backend: () => ProfileBackend) => [
  http.all(/\/api\/v1\/me\/profile(\/.*)?$/, async ({ request }) => {
    const body = request.method === 'GET' ? undefined : await request.json().catch(() => undefined);
    const reply = backend().handle(request.method, new URL(request.url).pathname, body);
    if (!reply) return HttpResponse.json({ code: 'not_found' }, { status: 404 });
    if (reply.status === 204) return new HttpResponse(null, { status: 204 });
    const problem =
      reply.status >= 400 ? { 'Content-Type': 'application/problem+json' } : undefined;
    return HttpResponse.json(reply.body as Record<string, unknown>, {
      status: reply.status,
      headers: problem,
    });
  }),
];

export const handlers = [
  getSystemGetClientConfigMockHandler(CLIENT_CONFIG),
  getIdentityAuthenticateTelegramMockHandler({ ...TOKENS, is_new: false, user: ME }),
  getIdentityRefreshSessionMockHandler(TOKENS),
  getIdentityLogoutMockHandler(),
  getIdentityGetMeMockHandler(ME),
  patchMe(ME),
  getIdentityAcceptConsentsMockHandler(accepted(ME)),
  getNotificationsGrantTelegramWriteAccessMockHandler(WRITE_ACCESS),
  getNotificationsListNotificationsMockHandler(({ request }) =>
    notificationsFor(request.headers.get('Accept-Language')),
  ),
  getNotificationsMarkNotificationsReadMockHandler({ unread_count: 0 }),
  getNotificationsGetNotificationSettingsMockHandler(NOTIFICATION_SETTINGS),
  // названия городов, районов и категорий — на языке запроса, как у backend
  getGeoListCitiesMockHandler(({ request }) => citiesFor(request.headers.get('Accept-Language'))),
  getGeoListDistrictsMockHandler(({ request }) =>
    districtsFor(request.headers.get('Accept-Language')),
  ),
  getCatalogListCategoriesMockHandler(({ request }) =>
    categoriesFor(request.headers.get('Accept-Language')),
  ),
  ...profileHandlers(() => new ProfileBackend()),
];

export const server = setupServer(...handlers);
