// Бейджи таббара (DEVELOPMENT_PLAN 6.4) — новые отклики и непрочитанные сообщения: при открытии,
// при возврате в приложение и раз в минуту; гостю — без запросов. Отдельно от диалогов: оболочку
// читает первый экран (бюджет 0.21b), и клиент переписки с ним не грузится.
import { getSession, getViewsGetBadgesQueryKey, viewsGetBadges } from '@sosed/api-client';
import { useQuery } from '@tanstack/react-query';

export const BADGES_POLL_MS = 60_000;

/** «Заявки N» (новые отклики) и «Сообщения N» (непрочитанные). */
export function useBadges() {
  return useQuery({
    queryKey: getViewsGetBadgesQueryKey(),
    queryFn: ({ signal }) => viewsGetBadges({ signal }),
    enabled: getSession() !== null,
    refetchInterval: BADGES_POLL_MS,
    refetchOnWindowFocus: true,
  });
}
