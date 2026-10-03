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
  getIdentityUpdatePrivacyMockHandler,
  getNotificationsGetNotificationSettingsMockHandler,
  getNotificationsGrantTelegramWriteAccessMockHandler,
  getNotificationsListNotificationsMockHandler,
  getNotificationsMarkNotificationsReadMockHandler,
  getSearchCountByCategoryMockHandler,
  getSearchCountSpecialistsMockHandler,
  getSearchListSpecialistsMockHandler,
  getSearchSuggestMockHandler,
  getSystemGetClientConfigMockHandler,
} from '@sosed/api-client/mocks';
import type { MeOut, MeUpdateIn, PrivacyIn, TokensOut } from '@sosed/api-client';
import { HttpResponse, http } from 'msw';
import { setupServer } from 'msw/node';

import {
  CLIENT_CONFIG,
  ME,
  NOTIFICATION_SETTINGS,
  WRITE_ACCESS,
  CATEGORY_COUNTS,
  accepted,
  cardReply,
  cardsFor,
  categoriesFor,
  citiesFor,
  districtsFor,
  notificationsFor,
  searchFound,
  searchPage,
  suggestFor,
} from './fixtures.ts';
import type { BackendReply } from './backend.ts';
import { ChatBackend } from './chatBackend.ts';
import { FavoritesBackend } from './favoritesBackend.ts';
import { JobsBackend } from './jobsBackend.ts';
import { ProfileBackend } from './profileBackend.ts';
import { SafetyBackend } from './safetyBackend.ts';

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

/** PATCH /me/privacy (S43, 6.5): «Мой Telegram» — в `privacy` свежего /me. */
export const patchPrivacy = (me: MeOut) =>
  getIdentityUpdatePrivacyMockHandler(async ({ request }) => {
    const body = (await request.json()) as PrivacyIn;
    return {
      ...me,
      privacy: { show_telegram: body.show_telegram ?? me.privacy.show_telegram },
    };
  });

/** Ответ фейка backend как HTTP: 204 без тела, ошибки — problem+json. */
function respond(reply: BackendReply | null) {
  if (!reply) return HttpResponse.json({ code: 'not_found' }, { status: 404 });
  if (reply.status === 204) return new HttpResponse(null, { status: 204 });
  const problem = reply.status >= 400 ? { 'Content-Type': 'application/problem+json' } : undefined;
  return HttpResponse.json(reply.body as Record<string, unknown>, {
    status: reply.status,
    headers: problem,
  });
}

/**
 * Кабинет исполнителя `/me/profile*` и его файлы `/media*` по фейку backend. По умолчанию —
 * свежий на каждый запрос: профиля нет. Тесты мастера S32a–c ставят свой — с памятью (server.use).
 */
export const profileHandlers = (backend: () => ProfileBackend) => [
  http.all(/\/api\/v1\/me\/profile(\/.*)?$/, async ({ request }) => {
    const body = request.method === 'GET' ? undefined : await request.json().catch(() => undefined);
    return respond(backend().handle(request.method, new URL(request.url).pathname, body));
  }),
  http.all(/\/api\/v1\/media(\/.*)?$/, async ({ request }) => {
    const body = request.method === 'GET' ? undefined : await request.json().catch(() => undefined);
    return respond(backend().media.handle(request.method, new URL(request.url).pathname, body));
  }),
];

/** Каталог S04–S06 (4.4): выдача, «Показать N» и числа дерева — из фикстур, как у backend. */
export const searchHandlers = [
  getSearchListSpecialistsMockHandler(({ request }) =>
    searchPage(new URL(request.url).searchParams, cardsFor(request.headers.get('Accept-Language'))),
  ),
  getSearchCountSpecialistsMockHandler(({ request }) => ({
    count: searchFound(
      new URL(request.url).searchParams,
      cardsFor(request.headers.get('Accept-Language')),
    ).length,
    capped: false,
  })),
  getSearchCountByCategoryMockHandler(CATEGORY_COUNTS),
  getSearchSuggestMockHandler(({ request }) =>
    suggestFor(
      new URL(request.url).searchParams.get('q') ?? '',
      request.headers.get('Accept-Language'),
    ),
  ),
];

/** Избранное S12 и сердечки (4.6) по фейку backend; по умолчанию — свежий на каждый запрос:
 *  список пуст. Тесты избранного ставят свой — с памятью (server.use). */
export const favoritesHandlers = (backend: () => FavoritesBackend) => [
  // сохранённые заявки (/me/favorites/job*) — у фейка заявок
  http.all(/\/api\/v1\/me\/favorites(\/profile\/[^/]+)?$/, ({ request }) =>
    respond(
      backend().handle(
        request.method,
        new URL(request.url).pathname,
        request.headers.get('Accept-Language'),
      ),
    ),
  ),
];

/** Карточка S08–S10 (4.5). После searchHandlers: путь `/specialists/:id` иначе перехватил бы
 *  `/specialists/count` и `/specialists/by-category`. */
export const cardHandlers = [
  http.get(/\/api\/v1\/specialists\/[^/]+(\/services|\/portfolio|\/reviews)?$/, ({ request }) =>
    respond(
      cardReply(new URL(request.url).pathname, request.headers.get('Accept-Language')) ?? null,
    ),
  ),
];

/** Заявки: создание (5.2), лента, «не интересно» и сохранённые (5.3), отклики и шаблоны (5.5)
 *  по фейку backend; по умолчанию — свежий на каждый запрос. Тесты мастера S20, ленты и откликов
 *  ставят свой — с памятью (server.use). */
const JOBS_API =
  /\/api\/v1\/(jobs(\/.*)?|me\/favorites\/jobs?(\/[^/]+)?|responses\/.+|me\/responses|me\/jobs|me\/response-templates(\/[^/]+)?|specialists\/[^/]+\/requests|me\/deals|deals\/.+|me\/deal-history|me\/reviews|reviews\/[^/]+\/reply)$/;

export const jobsHandlers = (backend: () => JobsBackend) => [
  http.all(JOBS_API, async ({ request }) => {
    const body = ['POST', 'PATCH'].includes(request.method)
      ? await request.json().catch(() => undefined)
      : undefined;
    return respond(
      backend().handle(
        request.method,
        new URL(request.url),
        body,
        request.headers.get('Idempotency-Key'),
        request.headers.has('Authorization'),
        request.headers.get('If-Match'),
      ),
    );
  }),
];

/** Переписка (6.4) и бейджи таббара по фейку backend; по умолчанию — свежий на каждый запрос:
 *  диалогов нет. Тесты S29 и S30 ставят свой — с памятью (server.use). */
const CHAT_API = /\/api\/v1\/(conversations(\/.*)?|me\/badges)$/;

export const chatHandlers = (backend: () => ChatBackend) => [
  http.all(CHAT_API, async ({ request }) => {
    const body =
      request.method === 'POST' ? await request.json().catch(() => undefined) : undefined;
    return respond(backend().handle(request.method, new URL(request.url), body));
  }),
];

/** Жалобы и блокировки (4.7) по фейку backend; по умолчанию — свежий на каждый запрос: никого не
 *  заблокировали. Тесты S44, S46 и меню S08, S30 ставят свой — с памятью (server.use). */
const SAFETY_API = /\/api\/v1\/(me\/blocks(\/[^/]+)?|reports)$/;

export const safetyHandlers = (backend: () => SafetyBackend) => [
  http.all(SAFETY_API, async ({ request }) => {
    const body =
      request.method === 'POST' ? await request.json().catch(() => undefined) : undefined;
    return respond(backend().handle(request.method, new URL(request.url).pathname, body));
  }),
];

export const handlers = [
  getSystemGetClientConfigMockHandler(CLIENT_CONFIG),
  getIdentityAuthenticateTelegramMockHandler({ ...TOKENS, is_new: false, user: ME }),
  getIdentityRefreshSessionMockHandler(TOKENS),
  getIdentityLogoutMockHandler(),
  getIdentityGetMeMockHandler(ME),
  patchMe(ME),
  patchPrivacy(ME),
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
  ...searchHandlers,
  ...cardHandlers,
  ...favoritesHandlers(() => new FavoritesBackend()),
  ...profileHandlers(() => new ProfileBackend()),
  ...jobsHandlers(() => new JobsBackend()),
  ...chatHandlers(() => new ChatBackend()),
  ...safetyHandlers(() => new SafetyBackend()),
];

export const server = setupServer(...handlers);
