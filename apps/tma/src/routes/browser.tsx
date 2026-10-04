// Что открыто вне Telegram (DEVELOPMENT_PLAN 8.1): гостевой просмотр карточки специалиста S08–S11 и
// заявки S15, веб-ссылки `/s/…`, `/j/…`, «Как удалить аккаунт» и правовые документы S48. Остальные
// экраны браузер не показывает (каталог, вход, создание — v1): вместо них — «Открыть в Telegram» с
// кодом startapp того же экрана (обратное routes/startapp.ts). Оболочка браузера — своим чанком.
import type { StartLink } from '@sosed/links';
import { encodeStartParam, isUuid } from '@sosed/links';
import { usePlatform } from '@sosed/platform';
import type { AnyRouteMatch } from '@tanstack/react-router';
import { lazy, Suspense } from 'react';

import { ACCOUNT_PATHS } from '../features/account/index.ts';
import { CARD_PATHS } from '../features/catalog/index.ts';
import { CREATE_PATHS, JOBS_PATHS } from '../features/jobs/index.ts';
import { MESSAGES_PATHS } from '../features/messages/index.ts';
import { LEGAL_PATH } from '../features/service/s48-legal/paths.ts';
import { AppShell } from '../features/shell/index.ts';
import { WEB_PATHS } from '../features/shell/web/paths.ts';

const BrowserShell = lazy(() =>
  import('../features/shell/web/BrowserShell.tsx').then((module) => ({
    default: module.BrowserShell,
  })),
);

/** Код startapp главной. */
const HOME_START = 'h';

/** Экраны, открытые в браузере (id маршрута — его путь). */
export const BROWSER_ROUTES: ReadonlySet<string> = new Set([
  WEB_PATHS.specialist,
  WEB_PATHS.job,
  WEB_PATHS.deletion,
  CARD_PATHS.profile,
  CARD_PATHS.services,
  CARD_PATHS.portfolio,
  CARD_PATHS.reviews,
  JOBS_PATHS.job,
  LEGAL_PATH,
]);

type Match = Pick<AnyRouteMatch, 'routeId' | 'params' | 'search'>;
type Param = (key: string) => string | null;

/** Экран → ссылка startapp: по id маршрута и его параметрам. */
const LINKS: [string, (param: Param, search: Record<string, unknown>) => StartLink | null][] = [
  [CARD_PATHS.profile, (param) => entity('specialist', param('profileId'))],
  [CARD_PATHS.services, (param) => entity('specialist', param('profileId'))],
  [CARD_PATHS.portfolio, (param) => entity('specialist', param('profileId'))],
  [CARD_PATHS.reviews, (param) => entity('specialist', param('profileId'))],
  // «Написать» и «Предложить заявку» гостя на S08 — мастер с прямым запросом: в Telegram — та же
  // карточка, создать заявку можно после входа
  [
    CREATE_PATHS.what,
    (_, search) =>
      typeof search['direct'] === 'string'
        ? entity('specialist', search['direct'])
        : { type: 'new_job' },
  ],
  [JOBS_PATHS.respond, (param) => entity('job', param('jobId'))],
  [JOBS_PATHS.manage, (param) => entity('job', param('jobId'))],
  [JOBS_PATHS.response, (param) => entity('job', param('jobId'))],
  [JOBS_PATHS.deal, (param) => entity('deal', param('dealId'))],
  [JOBS_PATHS.dispute, (param) => entity('dispute', param('dealId'))],
  [JOBS_PATHS.review, (param) => entity('deal', param('dealId'))],
  [MESSAGES_PATHS.chat, (param) => entity('chat', param('conversationId'))],
  [JOBS_PATHS.mine, () => ({ type: 'mine', section: 'jobs' })],
  [ACCOUNT_PATHS.settings, () => ({ type: 'mine', section: 'settings' })],
  [ACCOUNT_PATHS.delete, () => ({ type: 'mine', section: 'deletion' })],
];

function entity(
  type: 'specialist' | 'job' | 'deal' | 'dispute' | 'chat',
  id: string | null | undefined,
): StartLink | null {
  return id && isUuid(id) ? { type, id } : null;
}

/** Код startapp экрана, которого в браузере нет; `null` — экран открыт и в браузере. Неизвестный
 *  экран — главная. */
export function browserStart(match: Match | undefined): string | null {
  if (!match) return HOME_START;
  if (BROWSER_ROUTES.has(match.routeId)) return null;
  const params = match.params as Record<string, unknown>;
  const param: Param = (key) => {
    const value = params[key];
    return typeof value === 'string' ? value : null;
  };
  const build = LINKS.find(([routeId]) => routeId === match.routeId)?.[1];
  const link = build?.(param, (match.search ?? {}) as Record<string, unknown>);
  return link ? encodeStartParam(link) : HOME_START;
}

/** Корневой экран: в Telegram — оболочка с таббаром, в браузере — своя (чанк грузится только там). */
export function RootShell() {
  const platform = usePlatform();
  if (platform.kind !== 'browser') return <AppShell />;
  return (
    <Suspense fallback={null}>
      <BrowserShell blockedStart={browserStart} />
    </Suspense>
  );
}
