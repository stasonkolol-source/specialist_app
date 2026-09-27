// Адреса шагов онбординга и возврат после него (DEVELOPMENT_PLAN 1.5b). `next` — куда вести после
// S02c: цель deep link, открытой при запуске, или экран создающего действия, которое потребовало
// согласия. Без `next` — на главную.
import type { OnboardingStep } from '@sosed/hooks';

export const ONBOARDING_PATHS = {
  language: '/onboarding/language',
  intent: '/onboarding/intent',
  rules: '/onboarding/rules',
} as const satisfies Record<OnboardingStep, string>;

const PREFIX = '/onboarding/';

export interface OnboardingSearch {
  next?: string;
}

export function isOnboardingPath(pathname: string): boolean {
  return pathname.startsWith(PREFIX);
}

/**
 * Адрес возврата — только путь внутри приложения: `//host` и `/\host` браузер понял бы как другой
 * сайт. Сам онбординг и корень не нужны: после онбординга по умолчанию и так главная.
 */
export function safeNext(value: unknown): string | undefined {
  if (typeof value !== 'string' || !value.startsWith('/')) return undefined;
  if (value.startsWith('//') || value.startsWith('/\\') || value === '/') return undefined;
  if (isOnboardingPath(value)) return undefined;
  return value;
}

/** validateSearch маршрутов онбординга. */
export function onboardingSearch(search: Record<string, unknown>): OnboardingSearch {
  const next = safeNext(search.next);
  return next ? { next } : {};
}

/** Адрес шага со ссылкой возврата — для перехода до монтирования роутера (S01). */
export function onboardingHref(step: OnboardingStep, next?: string): string {
  const back = safeNext(next);
  const path = ONBOARDING_PATHS[step];
  return back ? `${path}?${new URLSearchParams({ next: back }).toString()}` : path;
}
