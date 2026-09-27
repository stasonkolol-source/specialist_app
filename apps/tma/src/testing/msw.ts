// MSW-обработчики orval с данными SPEC §4 (DEVELOPMENT_PLAN 0.21b): тесты Vitest видят API как
// настоящий backend. Для отдельного теста — server.use(<обработчик>) поверх этих.
import {
  getGeoListCitiesMockHandler,
  getIdentityAcceptConsentsMockHandler,
  getIdentityAuthenticateTelegramMockHandler,
  getIdentityGetMeMockHandler,
  getIdentityLogoutMockHandler,
  getIdentityRefreshSessionMockHandler,
  getIdentityUpdateMeMockHandler,
  getNotificationsGrantTelegramWriteAccessMockHandler,
  getSystemGetClientConfigMockHandler,
} from '@sosed/api-client/mocks';
import type { MeOut, MeUpdateIn, TokensOut } from '@sosed/api-client';
import { setupServer } from 'msw/node';

import { CLIENT_CONFIG, ME, WRITE_ACCESS, accepted, citiesFor } from './fixtures.ts';

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

export const handlers = [
  getSystemGetClientConfigMockHandler(CLIENT_CONFIG),
  getIdentityAuthenticateTelegramMockHandler({ ...TOKENS, is_new: false, user: ME }),
  getIdentityRefreshSessionMockHandler(TOKENS),
  getIdentityLogoutMockHandler(),
  getIdentityGetMeMockHandler(ME),
  patchMe(ME),
  getIdentityAcceptConsentsMockHandler(accepted(ME)),
  getNotificationsGrantTelegramWriteAccessMockHandler(WRITE_ACCESS),
  // названия городов — на языке запроса, как у backend
  getGeoListCitiesMockHandler(({ request }) => citiesFor(request.headers.get('Accept-Language'))),
];

export const server = setupServer(...handlers);
