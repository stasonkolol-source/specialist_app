// Deep link `startapp` → адрес экрана (DEVELOPMENT_PLAN 1.5b, ARCHITECTURE §11.4, ADR-0011).
// Разбор кода — packages/links (golden-векторы общие с backend). Цель без готового экрана и
// неизвестный код ведут на главную (до 4.8 — заглушка). Шаг экрана-цели добавляет в START_TARGETS
// свою строку: `s_` → S08 (4.5), `j_` → S15 (5.3), `n` → S20a и `m_jobs` → S22 (5.6), `d_` → S26
// (6.2), `p_` → S52 (6.1c), `c_` → S30 (6.4), `m_alerts`, `m_feed`, `m_availability`, `m_profile`
// (5.7), `ri_` → S56 (7.6а), `rv_` → S27, `m_responses` → S17, `m_portfolio` → S37; коды `g…`
// раздела «Вещи» — после MVP. Суффикс `_r<code>` — атрибуция: её записывает backend при входе
// (модуль growth), на выбор экрана он не влияет.
import type { MineSection, StartLink } from '@sosed/links';
import { parseStartParam } from '@sosed/links';

import { ACCOUNT_PATHS } from '../features/account/index.ts';
import { CABINET_PATHS } from '../features/specialist/index.ts';
import { profilePath } from '../features/catalog/index.ts';
import {
  CREATE_PATHS,
  JOBS_PATHS,
  dealPath,
  disputePath,
  inviteReviewPath,
  jobPath,
  reviewPath,
} from '../features/jobs/index.ts';
import { chatPath } from '../features/messages/index.ts';

const HOME = '/';

const MINE_TARGETS: Record<MineSection, string> = {
  jobs: JOBS_PATHS.mine,
  reviews: `${JOBS_PATHS.history}?tab=reviews`,
  settings: ACCOUNT_PATHS.settings,
  deletion: ACCOUNT_PATHS.delete,
  alerts: JOBS_PATHS.alerts,
  feed: `${JOBS_PATHS.feed}?alerts=true`,
  availability: CABINET_PATHS.availability,
  profile: CABINET_PATHS.home,
  // исходы своих откликов (уведомления «Выбрали другого», «Клиент отклонил», «закрыта без
  // выбора»): чужую закрытую заявку S15 исполнителю не открыть — карточка отклика в S17
  responses: JOBS_PATHS.responses,
  // отказ модерации по работе портфолио: исправить — в S37
  portfolio: CABINET_PATHS.portfolio,
};

/** Вариант ссылки с типом K: у сущностей тип — объединение (`job | specialist | …`), поэтому
 *  `Extract` их не находит — сужаем по каждому варианту. */
type LinkOf<L, K> = L extends { type: infer T } ? (K extends T ? L & { type: K } : never) : never;

type StartTargets = {
  [K in StartLink['type']]?: (link: LinkOf<StartLink, K>) => string;
};

export const START_TARGETS: StartTargets = {
  home: () => HOME,
  // /terms и /privacy бота (1.6): вкладка S48
  legal: (link) => `/legal/${link.document}`,
  // карточка специалиста S08: ссылки из выдачи, каналов и чатов диаспоры (4.5, шаринг — 7.4)
  specialist: (link) => profilePath(link.id),
  // заявка S15: кнопки уведомлений бота и ссылки из чатов (5.3); владельца S15 ведёт в S23 (5.6)
  job: (link) => jobPath(link.id),
  // мастер новой заявки S20a и «Мои заявки» S22: команды бота /new и /jobs (5.6)
  new_job: () => CREATE_PATHS.what,
  // «Мои заявки» S22 (`m_jobs`), «Сделки и отзывы» S28 на вкладке «Отзывы» (`m_reviews`, 7.3),
  // настройки S43 и удаление аккаунта S45 — кнопки `/settings` бота (4.9); подписки S18
  // (`m_alerts`), лента «по моим подпискам» (`m_feed`), «доступен сегодня» S38 (`m_availability`)
  // и кабинет S33 (`m_profile`) — кнопки уведомлений и команд `/feed`, `/alerts` (5.7)
  mine: (link) => MINE_TARGETS[link.section],
  // диалог S30: кнопка «Ответить» уведомления `message.received` (6.3b, 6.4)
  chat: (link) => chatPath(link.id),
  // сделка S26: кнопки уведомлений о сделке — «Открыть сделку» (6.2)
  deal: (link) => dealPath(link.id),
  // спор S52 сразу, без S26: «Есть проблема» под «Работа выполнена?», «Ответить» и «Посмотреть
  // решение» уведомлений о споре (6.1c)
  dispute: (link) => disputePath(link.id),
  // «отзыв до платформы» S56: ссылка-приглашение специалиста прошлому клиенту (S55, 7.6а)
  review_invite: (link) => inviteReviewPath(link.id),
  // форма отзыва S27 сразу: «Открыть форму отзыва» уведомления `review.request`
  review: (link) => reviewPath(link.id),
};

/** Адрес для кода `startapp`; `null` — приложение открыли без deep link. */
export function startTarget(param: string | null | undefined): string | null {
  if (!param) return null;
  const link = parseStartParam(param);
  if (!link) return HOME;
  const build = START_TARGETS[link.type] as ((link: StartLink) => string) | undefined;
  return build ? build(link) : HOME;
}
