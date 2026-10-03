// Адреса жалоб и блокировок (DEVELOPMENT_PLAN 4.7): список блокировок S44 — из настроек S43.
// Шторка жалобы S46 своего адреса не имеет: её открывает экран (openReport), рисует ReportHost.
export const SAFETY_PATHS = {
  blocked: '/settings/blocked',
} as const;
