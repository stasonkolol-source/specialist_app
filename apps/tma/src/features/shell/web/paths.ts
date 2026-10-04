// Браузерная оболочка (DEVELOPMENT_PLAN 8.1, ARCHITECTURE §11.4, §17.1): адреса страниц вне
// Telegram. Только константы — их импортирует первый чанк (маршруты); код ссылок — links.ts.

/** Веб-ссылки на сущности (`https://<домен>/s/<id>`, `/j/<id>`) и страница удаления аккаунта
 *  (требование Google Play — без входа). id — base62, как в коде startapp, или UUID. */
export const WEB_PATHS = {
  specialist: '/s/$code',
  job: '/j/$code',
  deletion: '/delete-account',
} as const;
