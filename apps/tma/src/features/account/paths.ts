// Адреса раздела «Профиль»: S31, удаление аккаунта S45 (DEVELOPMENT_PLAN 2.12a) и настройки S43
// (4.9; раздел приватности — 6.5). Помощь S47 — в фиче service.
export const ACCOUNT_PATHS = {
  home: '/profile',
  delete: '/profile/delete',
  settings: '/settings',
} as const;

/** «Сделки и отзывы» S28 (фича jobs, 7.3): строка «Моей активности». */
export const HISTORY_PATH = '/deals';
