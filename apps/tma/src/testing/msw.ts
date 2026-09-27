// MSW-обработчики orval с данными SPEC §4 (DEVELOPMENT_PLAN 0.21b): тесты Vitest видят API как
// настоящий backend. Для отдельного теста — server.use(<обработчик>) поверх этих.
import {
  getIdentityAuthenticateTelegramMockHandler,
  getIdentityGetMeMockHandler,
  getIdentityLogoutMockHandler,
  getIdentityRefreshSessionMockHandler,
  getIdentityUpdateMeMockHandler,
  getSystemGetClientConfigMockHandler,
} from '@sosed/api-client/mocks';
import type { MeUpdateIn, TokensOut } from '@sosed/api-client';
import { setupServer } from 'msw/node';

import { CLIENT_CONFIG, ME } from './fixtures.ts';

/** Origin API в тестах: fetch в Node не принимает относительные URL. */
export const API_ORIGIN = 'http://localhost';

export const TOKENS: TokensOut = {
  token_type: 'Bearer',
  access_token: 'test-access',
  access_expires_at: '2026-10-05T09:15:00Z',
  refresh_token: 'test-refresh',
  refresh_expires_at: '2026-10-12T09:00:00Z',
};

export const handlers = [
  getSystemGetClientConfigMockHandler(CLIENT_CONFIG),
  getIdentityAuthenticateTelegramMockHandler({ ...TOKENS, is_new: false, user: ME }),
  getIdentityRefreshSessionMockHandler(TOKENS),
  getIdentityLogoutMockHandler(),
  getIdentityGetMeMockHandler(ME),
  // PATCH /me применяет присланные поля, как backend (и page.route в e2e/api.ts)
  getIdentityUpdateMeMockHandler(async ({ request }) => {
    const { display_name, ui_locale } = (await request.json()) as MeUpdateIn;
    return {
      ...ME,
      display_name: display_name ?? ME.display_name,
      ui_locale: ui_locale ?? ME.ui_locale,
    };
  }),
];

export const server = setupServer(...handlers);
