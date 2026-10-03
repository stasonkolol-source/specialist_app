// Переходы мастера S32a–c. Каждое сохранение отвечает свежим профилем: он сразу ложится в кэш, и
// следующий шаг и S31 видят черновик без перечитывания.
import type { ProfileOut } from '@sosed/api-client';
import { color } from '@sosed/design-tokens';
import type { BecomeStep } from '@sosed/hooks';
import { myProfileQueryKey, useMyProfile } from '@sosed/hooks';
import type { BottomButtonProps } from '@sosed/platform';
import { useColorScheme, useMainButton } from '@sosed/platform';
import { useQueryClient } from '@tanstack/react-query';
import { useRouter } from '@tanstack/react-router';
import { useEffect } from 'react';

import { ACCOUNT_PATH, BECOME_PATHS } from './paths.ts';
import { useBecomeStore } from './store.ts';

export function useBecomeFlow() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const reset = useBecomeStore((state) => state.reset);

  const open = (step: BecomeStep, replace = false) =>
    void router.navigate({ to: BECOME_PATHS[step], replace });
  const saved = (profile: ProfileOut) => queryClient.setQueryData(myProfileQueryKey(), profile);

  return {
    open,
    saved,
    /** Отправлено на проверку: несохранённого ввода больше нет, дальше — S31 со статусом. */
    finish(profile: ProfileOut) {
      saved(profile);
      reset();
      void router.navigate({ to: ACCOUNT_PATH, replace: true });
    },
    /** «Назад» Telegram: на прошлый экран, а без истории — на шаг `fallback` или в S31. */
    back(fallback: BecomeStep | null) {
      if (router.history.canGoBack()) router.history.back();
      else if (fallback) open(fallback, true);
      else void router.navigate({ to: ACCOUNT_PATH, replace: true });
    },
  };
}

/**
 * Черновик профиля для шагов мастера. Профиль уже отправлен или опубликован — мастер пройден, в
 * S31. Профиля нет — на первый шаг (S32b–c открыли по ссылке); первому шагу он и не нужен
 * (`allowMissing`).
 */
export function useDraftProfile({ allowMissing = false }: { allowMissing?: boolean } = {}) {
  const router = useRouter();
  const query = useMyProfile();
  const profile = query.data;
  useEffect(() => {
    if (profile === null && !allowMissing) {
      void router.navigate({ to: BECOME_PATHS.type, replace: true });
    } else if (profile && profile.status !== 'draft') {
      void router.navigate({ to: ACCOUNT_PATH, replace: true });
    }
  }, [allowMissing, profile, router]);
  return { query, draft: profile?.status === 'draft' ? profile : undefined };
}

/** MainButton шага в цветах макета (акцент ui.css), а не в цвете кнопки темы Telegram. */
export function useStepButton(
  props: Pick<BottomButtonProps, 'text' | 'onClick' | 'loading' | 'visible'>,
) {
  const scheme = useColorScheme();
  const palette = color[scheme];
  return useMainButton({ ...props, color: palette.accent, textColor: palette['accent-ink'] });
}
