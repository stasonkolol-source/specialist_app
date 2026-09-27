// Онбординг S02a–c (DEVELOPMENT_PLAN 1.5b): какой шаг показать по GET /me и можно ли создавать.
// Решение одно на Mini App и мобильное приложение; навигацию делает оболочка.
// - язык и город (S02a) — пока нет города; намерение (S02b) — пока нет намерения;
// - правила (S02c) — пока нет согласия с действующими версиями: новая редакция правил
//   показывает S02c снова и вернувшемуся пользователю.
import type { MeOut } from '@sosed/api-client';
import { getSession, useIdentityGetMe } from '@sosed/api-client';

export const ONBOARDING_STEPS = ['language', 'intent', 'rules'] as const;
export type OnboardingStep = (typeof ONBOARDING_STEPS)[number];

type OnboardingState = Pick<MeOut, 'home_city_id' | 'intent' | 'consent_required'>;

/** Первый незавершённый шаг; `null` — онбординг пройден, можно на главную. */
export function onboardingStep(me: OnboardingState): OnboardingStep | null {
  if (me.home_city_id === null) return 'language';
  if (me.intent === null) return 'intent';
  if (me.consent_required) return 'rules';
  return null;
}

/**
 * Шаг после сохранённого `step`. Из S02a всегда идём в S02b — это один проход, намерение можно
 * поменять; S02c — только без действующего согласия (город и намерение правили повторно).
 */
export function nextOnboardingStep(
  step: OnboardingStep,
  me: OnboardingState,
): OnboardingStep | null {
  if (step === 'language') return 'intent';
  if (step === 'intent' && me.consent_required) return 'rules';
  return null;
}

/**
 * Можно ли создающее действие (заявка, отклик, сообщение). `unknown` — не вошли (браузер без
 * Telegram): сервер всё равно ответит 401, экран решает сам. Просмотр согласия не требует.
 */
export type ConsentGate = 'unknown' | 'required' | 'accepted';

export function consentGate(me: Pick<MeOut, 'consent_required'> | undefined): ConsentGate {
  if (!me) return 'unknown';
  return me.consent_required ? 'required' : 'accepted';
}

/** Гейт согласия по /me из кэша: вход при запуске (S01) кладёт туда пользователя. */
export function useConsentGate(): ConsentGate {
  const me = useIdentityGetMe({ query: { enabled: getSession() !== null } });
  return consentGate(me.data);
}
