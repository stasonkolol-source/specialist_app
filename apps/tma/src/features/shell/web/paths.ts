// Браузерная оболочка (DEVELOPMENT_PLAN 8.1, ARCHITECTURE §11.4, §17.1): адреса для ссылок вне
// Telegram и ссылки на бота. Пути — без кода экранов: их импортирует первый чанк (маршруты).
import { base62ToUuid, encodeStartParam, isUuid } from '@sosed/links';

/** Веб-ссылки на сущности (`https://<домен>/s/<id>`, `/j/<id>`) и страница удаления аккаунта
 *  (требование Google Play — без входа). id — base62, как в коде startapp, или UUID. */
export const WEB_PATHS = {
  specialist: '/s/$code',
  job: '/j/$code',
  deletion: '/delete-account',
} as const;

export type WebEntity = 'specialist' | 'job';

/** Экраны сущностей — маршруты фич catalog (S08) и jobs (S15); routes/browser.test.ts сверяет их
 *  с деревом маршрутов. */
export const ENTITY_PATHS: Record<WebEntity, (id: string) => string> = {
  specialist: (id) => `/specialists/${id}`,
  job: (id) => `/jobs/${id}`,
};

/** id сущности из веб-адреса; `null` — битая ссылка. */
export function entityId(code: string): string | null {
  return isUuid(code) ? code.toLowerCase() : base62ToUuid(code);
}

/** Код startapp сущности: карточка — `s_…`, заявка — `j_…` (packages/links). */
export function entityStart(type: WebEntity, id: string): string {
  return encodeStartParam({ type, id });
}

/** Бот Mini App (`VITE_TELEGRAM_BOT` при сборке, без @); пусто — ссылки на Telegram нет. */
export const TELEGRAM_BOT: string | null = import.meta.env.VITE_TELEGRAM_BOT?.trim() || null;

/** Ссылка `t.me/<бот>?startapp=<код>`: Telegram откроет Mini App сразу на экране кода. */
export function telegramLink(start: string, bot: string | null = TELEGRAM_BOT): string | null {
  return bot ? `https://t.me/${bot}?startapp=${start}` : null;
}
