// Deep link `startapp` → адрес экрана (DEVELOPMENT_PLAN 1.5b, ARCHITECTURE §11.4, ADR-0011).
// Разбор кода — packages/links (golden-векторы общие с backend). Цель без готового экрана и
// неизвестный код ведут на главную (до 4.8 — заглушка). Шаг экрана-цели добавляет в START_TARGETS
// свою строку: `s_` → S08 (4.5), `j_` → S15 (5.3), `d_` → S26 (6.2), `c_` → S30 (6.4); коды `g…`
// раздела «Вещи» — после MVP. Суффикс `_r<code>` — атрибуция: её записывает backend при входе
// (модуль growth), на выбор экрана он не влияет.
import type { StartLink } from '@sosed/links';
import { parseStartParam } from '@sosed/links';

const HOME = '/';

type StartTargets = {
  [K in StartLink['type']]?: (link: Extract<StartLink, { type: K }>) => string;
};

export const START_TARGETS: StartTargets = {
  home: () => HOME,
  // /terms и /privacy бота (1.6): вкладка S48
  legal: (link) => `/legal/${link.document}`,
};

/** Адрес для кода `startapp`; `null` — приложение открыли без deep link. */
export function startTarget(param: string | null | undefined): string | null {
  if (!param) return null;
  const link = parseStartParam(param);
  if (!link) return HOME;
  const build = START_TARGETS[link.type] as ((link: StartLink) => string) | undefined;
  return build ? build(link) : HOME;
}
