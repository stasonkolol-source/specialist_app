// Deep link `startapp` → адрес экрана (DEVELOPMENT_PLAN 1.5b, ARCHITECTURE §11.4, ADR-0011).
// Разбор кода — packages/links (golden-векторы общие с backend). Цель без готового экрана и
// неизвестный код ведут на главную (до 4.8 — заглушка). Шаг экрана-цели добавляет в START_TARGETS
// свою строку: `s_` → S08 (4.5), `j_` → S15 (5.3), `d_` → S26 (6.2), `c_` → S30 (6.4); коды `g…`
// раздела «Вещи» — после MVP. Суффикс `_r<code>` — атрибуция: её записывает backend при входе
// (модуль growth), на выбор экрана он не влияет.
import type { StartLink } from '@sosed/links';
import { parseStartParam } from '@sosed/links';

import { profilePath } from '../features/catalog/index.ts';
import { jobPath } from '../features/jobs/index.ts';

const HOME = '/';

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
  // заявка S15: кнопки уведомлений бота и ссылки из чатов (5.3); владельцу — S23 с 5.6
  job: (link) => jobPath(link.id),
};

/** Адрес для кода `startapp`; `null` — приложение открыли без deep link. */
export function startTarget(param: string | null | undefined): string | null {
  if (!param) return null;
  const link = parseStartParam(param);
  if (!link) return HOME;
  const build = START_TARGETS[link.type] as ((link: StartLink) => string) | undefined;
  return build ? build(link) : HOME;
}
