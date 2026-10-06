// Переходы онбординга: следующий шаг с тем же адресом возврата и выход по окончании. Шаги и выход
// заменяют запись истории: «Назад» после завершения не возвращает в онбординг. Новый пользователь
// с намерением «Я специалист» или «Ищу подработку» выходит сразу в мастер профиля S32a с отмеченным
// типом (UX_GUIDANCE №6), а не на клиентскую Главную; Главная остаётся под ним — «Назад» туда.
import type { MeOut, ProfileKind, UserIntent } from '@sosed/api-client';
import { getIdentityGetMeQueryKey } from '@sosed/api-client';
import type { OnboardingStep } from '@sosed/hooks';
import { nextOnboardingStep } from '@sosed/hooks';
import { color } from '@sosed/design-tokens';
import type { BottomButtonProps } from '@sosed/platform';
import { useColorScheme, useMainButton } from '@sosed/platform';
import { useQueryClient } from '@tanstack/react-query';
import { useRouter, useSearch } from '@tanstack/react-router';

import { ONBOARDING_PATHS, safeNext } from './paths.ts';
import { useOnboardingStore } from './store.ts';

/** Первый шаг мастера «Стать специалистом» (маршрут features/specialist, `?kind=` — тип). */
const BECOME_TYPE_PATH = '/become/type';

/** Тип профиля по намерению S02b; клиенту мастер не нужен. */
export function becomeKind(intent: UserIntent | null | undefined): ProfileKind | null {
  return intent === 'pro' || intent === 'casual' ? intent : null;
}

export function useOnboardingFlow() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const reset = useOnboardingStore((state) => state.reset);
  const search: { next?: unknown } = useSearch({ strict: false });
  const next = safeNext(search.next);

  const open = (step: OnboardingStep, replace = false) =>
    void router.navigate({ to: ONBOARDING_PATHS[step], search: next ? { next } : {}, replace });

  /** `kind` — онбординг пройден впервые специалистом: Главная, а поверх неё — S32a. Цель deep
   *  link или создающего действия (`next`) важнее. */
  const finish = (kind: ProfileKind | null = null) => {
    reset();
    if (next || !kind) {
      void router.navigate({ href: next ?? '/', replace: true });
      return;
    }
    void router
      .navigate({ href: '/', replace: true })
      .then(() => router.navigate({ to: BECOME_TYPE_PATH, search: { kind } }));
  };

  return {
    open,
    finish,
    /** Ответ PATCH /me и POST /me/consents — тот же MeOut: кэш /me обновлён, дальше — нужный шаг.
     *  `firstRun` — согласий до этого не было: человек только что прошёл онбординг целиком. */
    saved(step: OnboardingStep, me: MeOut, firstRun = false) {
      queryClient.setQueryData(getIdentityGetMeQueryKey(), me);
      const following = nextOnboardingStep(step, me);
      if (following) open(following, true);
      else finish(firstRun ? becomeKind(me.intent) : null);
    },
    /** «Назад» Telegram: на прошлый экран, а без истории (открыли сразу этот шаг) — на `fallback`. */
    back(fallback: OnboardingStep | null) {
      if (router.history.canGoBack()) router.history.back();
      else if (fallback) open(fallback, true);
    },
  };
}

/** MainButton шага в цветах макета (акцент ui.css), а не в цвете кнопки темы Telegram. */
export function useStepButton(props: Pick<BottomButtonProps, 'text' | 'onClick' | 'loading'>) {
  const scheme = useColorScheme();
  const palette = color[scheme];
  return useMainButton({ ...props, color: palette.accent, textColor: palette['accent-ink'] });
}
