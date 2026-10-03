// Адреса раздела «Профиль»: S31, удаление аккаунта S45 (DEVELOPMENT_PLAN 2.12a) и настройки S43
// (4.9; раздел приватности — 6.5). Помощь S47 — в фиче service, заблокированные S44 — в фиче
// safety (4.7): фичи друг друга не импортируют — адрес строкой.
export const ACCOUNT_PATHS = {
  home: '/profile',
  delete: '/profile/delete',
  settings: '/settings',
  blocked: '/settings/blocked',
} as const;

/** «Сделки и отзывы» S28 (фича jobs, 7.3): строка «Моей активности». */
export const HISTORY_PATH = '/deals';
