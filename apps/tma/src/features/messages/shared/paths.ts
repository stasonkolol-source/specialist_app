// Адреса «Сообщений» (DEVELOPMENT_PLAN 6.4): список S29 (вкладка таббара) и диалог S30 — из
// списка, из «Написать» на S08 и S24 и по deep link `c_` (routes/startapp.ts).
export const MESSAGES_PATHS = {
  list: '/messages',
  chat: '/messages/$conversationId',
} as const;

export const chatPath = (conversationId: string) => `/messages/${conversationId}`;

/** Своя заявка клиента S23 (фича jobs, 5.6): «К откликам» в диалоге по отклику. */
export const managedJobPath = (jobId: string) => `/jobs/${jobId}/manage`;

/** Сделка S26 (фича jobs, 6.2): полоса сделки в диалоге; ждущее предложение второй стороне — S53. */
export const dealPath = (dealId: string) => `/deals/${dealId}`;

/** Карточка специалиста S08 (фича catalog, 4.5): шапка диалога ведёт на неё. */
export const profilePath = (profileId: string) => `/specialists/${profileId}`;

export interface ChatSearch {
  /** Открыть шторку «Поделиться контактом» (S54): кнопка в сделке S26. */
  share?: true;
}

export function chatSearch(search: Record<string, unknown>): ChatSearch {
  return search.share === true || search.share === 'true' ? { share: true } : {};
}
