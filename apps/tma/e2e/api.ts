// API для e2e: ответы из фикстур SPEC §4 через page.route — тот же контракт, что MSW в Vitest,
// без service worker. Неописанный запрос к /api — ошибка теста.
import type {
  ClientConfigOut,
  MeOut,
  NotificationPageOut,
  NotificationSettingsIn,
  NotificationSettingsOut,
} from '@sosed/api-client';
import type { Page, Request, Route } from '@playwright/test';

import {
  CLIENT_CONFIG,
  DELETION_EXECUTE_AFTER,
  DELETION_REQUESTED_AT,
  ME,
  NOTIFICATION_SETTINGS,
  WRITE_ACCESS,
  accepted,
  CATEGORY_COUNTS,
  E2E_AVAILABLE_UNTIL,
  cardReply,
  cardsFor,
  categoriesFor,
  citiesFor,
  districtsFor,
  notificationsFor,
  shareReply,
  searchFound,
  searchPage,
  suggestFor,
} from '../src/testing/fixtures.ts';
import { ChatBackend } from '../src/testing/chatBackend.ts';
import { FavoritesBackend } from '../src/testing/favoritesBackend.ts';
import { JobsBackend } from '../src/testing/jobsBackend.ts';
import { ProfileBackend } from '../src/testing/profileBackend.ts';
import { SafetyBackend } from '../src/testing/safetyBackend.ts';

/** «Фото работы» для загрузок и CDN: PNG 8×6, мягкий зелёный градиент — одинаковый везде. */
export const PHOTO_PNG = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAgAAAAGCAIAAABxZ0isAAAAeklEQVR42g3JoQ4AIQgA0PvTSyaTyWRyY8qcc+wygUAgEPj' +
    'C89X3vAyJR2YsvCrvxqczTf6eVyDJyIJFVpXd5HShKTcUko6sWHRV3U1PV5p6wyDZyIbFVrXd7HSjaTccko/sWHxV381Pd5p+' +
    'IyDFyIElVo3d4vSgGd8PB39PsTTSlHEAAAAASUVORK5CYII=',
  'base64',
);

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
  /** GET /me/notification-settings; по умолчанию бот писать не может (баннер S42). PUT (S43)
   *  заменяет их, как backend. */
  notificationSettings?: NotificationSettingsOut;
  /** Кабинет исполнителя `/me/profile*` и его файлы `/media*` с памятью; по умолчанию — профиля
   *  нет. Его приглашения на «отзыв до платформы» отвечают и на форму S56 `/review-invites/*`. */
  profile?: ProfileBackend;
  /** Избранное `/me/favorites*` с памятью (4.6); по умолчанию — пусто. */
  favorites?: FavoritesBackend;
  /** Заявки `/jobs*` с памятью: создание (5.2), лента, счётчик и «не интересно» (5.3), отклики
   *  и шаблоны откликов (5.5), подписки на заявки (5.7). */
  jobs?: JobsBackend;
  /** Переписка `/conversations*` и бейджи таббара `/me/badges` с памятью (6.4); по умолчанию —
   *  диалогов нет. */
  chat?: ChatBackend;
  /** Жалобы `/reports` и блокировки `/me/blocks*` с памятью (4.7); по умолчанию — никого не
   *  заблокировали. Переписка спрашивает у него, закрыта ли она блокировкой. */
  safety?: SafetyBackend;
  /** Задержка каждого ответа API, мс: замер холодного старта (coldstart.spec.ts). */
  delayMs?: number;
  /** Свои ответы по ключу «METHOD /api/v1/…»: проверяются раньше стандартных. */
  handlers?: Record<string, (route: Route) => Promise<void>>;
  /** Что приложение прислало в PATCH /me, POST /me/consents, POST /me/telegram/write-access,
   *  POST /me/notifications/read и PUT /me/notification-settings. */
  sent?: SentRequests;
}

export interface SentRequests {
  patch: unknown[];
  consents: unknown[];
  writeAccess: number;
  read: unknown[];
  settings: NotificationSettingsIn[];
}

export const sentRequests = (): SentRequests => ({
  patch: [],
  consents: [],
  writeAccess: 0,
  read: [],
  settings: [],
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
    profile = new ProfileBackend(),
    favorites = new FavoritesBackend([], E2E_AVAILABLE_UNTIL),
    jobs = new JobsBackend(),
    chat = new ChatBackend(),
    safety = new SafetyBackend(),
    delayMs = 0,
    handlers = {},
    sent = sentRequests(),
  }: MockApiOptions = {},
): Promise<void> {
  // загрузки media (2.11): PUT в «хранилище» по presigned-ссылке и варианты готового фото — того
  // же origin, что приложение (ссылки отдаёт MediaBackend)
  await page.route('**/storage/**', (route) =>
    route.request().method() === 'PUT'
      ? route.fulfill({ status: 200, headers: { ETag: '"e2e"' } })
      : route.fulfill({ status: 405 }),
  );
  await page.route('**/cdn/**', (route) =>
    route.fulfill({ status: 200, contentType: 'image/png', body: PHOTO_PNG }),
  );
  // пользователь с памятью, как на сервере: онбординг меняет его шаг за шагом
  let user = me;
  chat.safety ??= safety;
  let settings = notificationSettings;
  await page.route('**/api/v1/**', async (route) => {
    if (delayMs > 0) await new Promise((resolve) => setTimeout(resolve, delayMs));
    const request = route.request();
    const url = new URL(request.url());
    const key = `${request.method()} ${url.pathname}`;
    const handler = handlers[key];
    if (handler) return handler(route);
    const language = request.headers()['accept-language'] ?? null;
    if (url.pathname.startsWith('/api/v1/me/profile')) {
      if (!authorized(request)) return route.fulfill(json(NOT_AUTHENTICATED, 401));
      const body: unknown = request.method() === 'GET' ? undefined : request.postDataJSON();
      const reply = profile.handle(request.method(), url.pathname, body);
      if (reply?.status === 204) return route.fulfill({ status: 204 });
      if (reply) return route.fulfill(json(reply.body, reply.status));
    }
    // сохранённые заявки (5.3) — у фейка заявок, ниже
    if (
      url.pathname.startsWith('/api/v1/me/favorites') &&
      !url.pathname.startsWith('/api/v1/me/favorites/job')
    ) {
      if (!authorized(request)) return route.fulfill(json(NOT_AUTHENTICATED, 401));
      const reply = favorites.handle(request.method(), url.pathname, language);
      if (reply?.status === 204) return route.fulfill({ status: 204 });
      if (reply) return route.fulfill(json(reply.body, reply.status));
    }
    if (url.pathname.startsWith('/api/v1/media')) {
      if (!authorized(request)) return route.fulfill(json(NOT_AUTHENTICATED, 401));
      const body: unknown = request.method() === 'GET' ? undefined : request.postDataJSON();
      const reply = profile.media.handle(request.method(), url.pathname, body);
      if (reply?.status === 204) return route.fulfill({ status: 204 });
      if (reply) return route.fulfill(json(reply.body, reply.status));
    }
    // заявки: создание с ключом идемпотентности и созданная заявка для S21 (5.2); лента, счётчик
    // и «не интересно» (5.3) — лента открыта и гостю; отклики и шаблоны откликов (5.5), подписки
    // на заявки (5.7); сделки (6.2), история сделок и отзывы (7.3)
    if (
      url.pathname === '/api/v1/jobs' ||
      url.pathname.startsWith('/api/v1/jobs/') ||
      url.pathname.startsWith('/api/v1/me/favorites/job') ||
      url.pathname.startsWith('/api/v1/responses/') ||
      url.pathname === '/api/v1/me/responses' ||
      url.pathname === '/api/v1/me/jobs' ||
      url.pathname === '/api/v1/me/deals' ||
      url.pathname.startsWith('/api/v1/deals/') ||
      // сделки и отзывы S28 (7.3)
      url.pathname === '/api/v1/me/deal-history' ||
      url.pathname === '/api/v1/me/reviews' ||
      url.pathname.startsWith('/api/v1/reviews/') ||
      /^\/api\/v1\/specialists\/[^/]+\/requests$/.test(url.pathname) ||
      url.pathname.startsWith('/api/v1/me/response-templates') ||
      url.pathname.startsWith('/api/v1/me/job-alerts')
    ) {
      const body: unknown = ['POST', 'PATCH'].includes(request.method())
        ? request.postDataJSON()
        : undefined;
      const reply = jobs.handle(
        request.method(),
        url,
        body,
        request.headers()['idempotency-key'] ?? null,
        authorized(request),
        request.headers()['if-match'] ?? null,
      );
      if (reply?.status === 204) return route.fulfill({ status: 204 });
      if (reply) return route.fulfill(json(reply.body, reply.status));
    }
    // форма «отзыва до платформы» S56 по ссылке `ri_` и отзыв по ней (7.6а): форму видит и гость,
    // отправить — только вошедший; приглашения — у фейка кабинета (S55)
    if (url.pathname.startsWith('/api/v1/review-invites/')) {
      const body: unknown = request.method() === 'POST' ? request.postDataJSON() : undefined;
      const reply = profile.invites.handlePublic(
        request.method(),
        url.pathname,
        body,
        authorized(request),
        language,
      );
      if (reply) return route.fulfill(json(reply.body, reply.status));
    }
    // «Поделиться» (7.4): вошедшему — с кодом `_r` и карточкой, гостю — ссылка
    if (url.pathname === '/api/v1/share' && request.method() === 'POST') {
      const reply = shareReply(request.postDataJSON(), authorized(request));
      return route.fulfill(json(reply.body, reply.status));
    }
    // жалобы S46 и блокировки S44 (4.7): только вошедшему
    if (url.pathname.startsWith('/api/v1/me/blocks') || url.pathname === '/api/v1/reports') {
      if (!authorized(request)) return route.fulfill(json(NOT_AUTHENTICATED, 401));
      const body: unknown = request.method() === 'POST' ? request.postDataJSON() : undefined;
      const reply = safety.handle(request.method(), url.pathname, body);
      if (reply?.status === 204) return route.fulfill({ status: 204 });
      if (reply) return route.fulfill(json(reply.body, reply.status));
    }
    // переписка S29–S30 и бейджи таббара (6.4): только вошедшему
    if (url.pathname.startsWith('/api/v1/conversations') || url.pathname === '/api/v1/me/badges') {
      if (!authorized(request)) return route.fulfill(json(NOT_AUTHENTICATED, 401));
      const body: unknown = request.method() === 'POST' ? request.postDataJSON() : undefined;
      const reply = chat.handle(request.method(), url, body);
      if (reply?.status === 204) return route.fulfill({ status: 204 });
      if (reply) return route.fulfill(json(reply.body, reply.status));
    }
    // карточка специалиста S08–S10 (4.5): «Сегодня до 20:00» — как в выдаче (часы E2E_NOW)
    const card =
      request.method() === 'GET'
        ? cardReply(url.pathname, language, E2E_AVAILABLE_UNTIL, url.searchParams)
        : null;
    if (card) return route.fulfill(json(card.body, card.status));
    // районы города: /cities/{id}/districts — названия на языке запроса
    if (/^GET \/api\/v1\/cities\/\d+\/districts$/.test(key)) {
      return route.fulfill(json(districtsFor(language)));
    }
    switch (key) {
      case 'GET /api/v1/client-config':
        return route.fulfill(json(config));
      case 'GET /api/v1/cities':
        return route.fulfill(json(citiesFor(language)));
      case 'GET /api/v1/categories':
        return route.fulfill(json(categoriesFor(language)));
      // каталог S04–S06 (4.4): выдача из фикстур SPEC §4; «Свободен сегодня» — до 20:00 по
      // Белграду при часах браузера E2E_NOW (catalog.spec.ts)
      case 'GET /api/v1/specialists':
        return route.fulfill(
          json(searchPage(url.searchParams, cardsFor(language, E2E_AVAILABLE_UNTIL))),
        );
      case 'GET /api/v1/specialists/count':
        return route.fulfill(
          json({
            count: searchFound(url.searchParams, cardsFor(language, E2E_AVAILABLE_UNTIL)).length,
            capped: false,
          }),
        );
      case 'GET /api/v1/specialists/by-category':
        return route.fulfill(json(CATEGORY_COUNTS));
      // подсказки при вводе на Главной S03 (4.8)
      case 'GET /api/v1/suggest':
        return route.fulfill(json(suggestFor(url.searchParams.get('q') ?? '', language)));
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
      // S45: grace 7 дней; повтор — тот же срок, отмена идемпотентна
      case 'POST /api/v1/me/deletion': {
        if (!authorized(request)) return route.fulfill(json(NOT_AUTHENTICATED, 401));
        const execute = user.deletion_scheduled_at ?? DELETION_EXECUTE_AFTER;
        user = { ...user, deletion_scheduled_at: execute };
        return route.fulfill(json({ requested_at: DELETION_REQUESTED_AT, execute_after: execute }));
      }
      case 'DELETE /api/v1/me/deletion':
        if (!authorized(request)) return route.fulfill(json(NOT_AUTHENTICATED, 401));
        user = { ...user, deletion_scheduled_at: null };
        return route.fulfill({ status: 204 });
      case 'POST /api/v1/me/telegram/write-access':
        if (!authorized(request)) return route.fulfill(json(NOT_AUTHENTICATED, 401));
        sent.writeAccess += 1;
        // как backend: разрешение видно и в настройках уведомлений (S58 «Готово!», 7.5)
        settings = { ...settings, telegram: WRITE_ACCESS };
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
        return route.fulfill(json(settings));
      // S43: настройки целиком; группы, которых нет в теле, сервер вернул бы к умолчаниям
      case 'PUT /api/v1/me/notification-settings': {
        if (!authorized(request)) return route.fulfill(json(NOT_AUTHENTICATED, 401));
        const body = request.postDataJSON() as NotificationSettingsIn;
        sent.settings.push(body);
        settings = {
          ...settings,
          groups: settings.groups.map((row) => ({
            ...row,
            ...body.groups.find((sentRow) => sentRow.group === row.group),
          })),
          quiet_hours: { ...settings.quiet_hours, enabled: body.quiet_hours.enabled },
        };
        return route.fulfill(json(settings));
      }
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
