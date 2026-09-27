// Переходы онбординга: следующий шаг с тем же адресом возврата и выход по окончании. Выход
// заменяет запись истории: «Назад» с главной не возвращает в онбординг.
import type { MeOut } from '@sosed/api-client';
import { getIdentityGetMeQueryKey } from '@sosed/api-client';
import type { OnboardingStep } from '@sosed/hooks';
import { nextOnboardingStep } from '@sosed/hooks';
import { tokens } from '@sosed/design-tokens';
import type { BottomButtonProps } from '@sosed/platform';
import { useColorScheme, useMainButton } from '@sosed/platform';
import { useQueryClient } from '@tanstack/react-query';
import { useRouter, useSearch } from '@tanstack/react-router';

import { ONBOARDING_PATHS, safeNext } from './paths.ts';
import { useOnboardingStore } from './store.ts';

export function useOnboardingFlow() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const reset = useOnboardingStore((state) => state.reset);
  const search: { next?: unknown } = useSearch({ strict: false });
  const next = safeNext(search.next);

  const open = (step: OnboardingStep, replace = false) =>
    void router.navigate({ to: ONBOARDING_PATHS[step], search: next ? { next } : {}, replace });

  const finish = () => {
    reset();
    void router.navigate({ href: next ?? '/', replace: true });
  };

  return {
    open,
    finish,
    /** Ответ PATCH /me и POST /me/consents — тот же MeOut: кэш /me обновлён, дальше — нужный шаг. */
    saved(step: OnboardingStep, me: MeOut) {
      queryClient.setQueryData(getIdentityGetMeQueryKey(), me);
      const following = nextOnboardingStep(step, me);
      if (following) open(following);
      else finish();
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
  const palette = tokens.color[scheme];
  return useMainButton({ ...props, color: palette.accent, textColor: palette['accent-ink'] });
}
