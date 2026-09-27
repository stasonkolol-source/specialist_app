// Охрана маршрутов (DEVELOPMENT_PLAN 1.5b). Решение — packages/hooks (одно для Mini App и
// мобильного приложения), здесь — только переход. /me берётся из кэша: его кладёт вход при запуске
// (S01), а шаги онбординга и S02c обновляют ответом сервера.
import type { MeOut } from '@sosed/api-client';
import { getIdentityGetMeQueryKey } from '@sosed/api-client';
import { consentGate } from '@sosed/hooks';
import type { QueryClient } from '@tanstack/react-query';
import type { ParsedLocation } from '@tanstack/react-router';
import { redirect } from '@tanstack/react-router';

import { ONBOARDING_PATHS } from '../features/onboarding/index.ts';

export interface RouterContext {
  queryClient: QueryClient;
}

interface GuardArgs {
  context: RouterContext;
  location: ParsedLocation;
  preload: boolean;
}

const meOf = (context: RouterContext) =>
  context.queryClient.getQueryData<MeOut>(getIdentityGetMeQueryKey());

/**
 * beforeLoad экранов создающих действий (S20a; дальше отклик S16, подписка S19, профиль S32…):
 * без согласия с действующими правилами — S02c, после него — обратно сюда. Просмотр согласия не
 * требует. Гость без сессии проходит: создать он всё равно не сможет (401), экран покажет вход.
 * Предзагрузка чанков (таббар) не перенаправляет.
 */
export function requireConsent({ context, location, preload }: GuardArgs): void {
  if (preload || consentGate(meOf(context)) !== 'required') return;
  throw redirect({ to: ONBOARDING_PATHS.rules, search: { next: location.href }, replace: true });
}

/** beforeLoad шагов онбординга: выбор сохраняется в /me — без входа им нечего делать. */
export function requireUser({ context, preload }: GuardArgs): void {
  if (!preload && !meOf(context)) throw redirect({ to: '/', replace: true });
}
