// Первый экран после входа (S01, DEVELOPMENT_PLAN 1.5b):
// - новый пользователь — онбординг S02a → S02b → S02c, недоделанный — с того шага, где остановился;
//   новая редакция правил — только S02c; после онбординга — цель запуска;
// - цель запуска — экран deep link (routes/startapp.ts) или адрес, открытый внутри приложения
//   (перезагрузка в клиенте Telegram оставляет человека на месте); иначе главная.
// Гость (браузер без Telegram, initData не принят) онбординг не проходит: смотреть можно и так.
import type { MeOut } from '@sosed/api-client';
import { onboardingStep } from '@sosed/hooks';
import type { Platform } from '@sosed/platform';

import { isOnboardingPath, onboardingHref, safeNext } from '../features/onboarding/index.ts';

const HOME = '/';

export interface LaunchLocation {
  pathname: string;
  /** Путь с параметрами, как в адресе. */
  href: string;
  /** Строка параметров `?next=…`. */
  search: string;
}

/** Адрес, на который перейти до первого экрана; `null` — открытый адрес подходит. */
export function launchHref(
  user: Pick<MeOut, 'home_city_id' | 'intent' | 'consent_required'> | null,
  location: LaunchLocation,
  deepLink: string | null,
): string | null {
  const { pathname, href } = location;
  // При запуске из Telegram в hash — launch params, а не путь: такой адрес не «внутри приложения»
  const inApp = pathname.startsWith('/') && pathname !== HOME;
  const target =
    deepLink ??
    (inApp && isOnboardingPath(pathname)
      ? (safeNext(new URLSearchParams(location.search).get('next')) ?? HOME)
      : inApp
        ? href
        : HOME);
  const step = user ? onboardingStep(user) : null;
  const destination = step ? onboardingHref(step, target) : target;
  return destination === href ? null : destination;
}

/**
 * Приложение открыли из Telegram (в hash — launch params), а не перезагрузили экран внутри клиента:
 * только тогда действует deep link, иначе перезагрузка снова открыла бы его. В mock-режиме
 * (разработка, e2e) каждая загрузка страницы — запуск.
 */
export function openedByTelegram(kind: Platform['kind'], hash: string): boolean {
  if (kind === 'mock') return true;
  return /(?:^#|&)tgWebApp(?:Data|Version)=/.test(hash);
}
