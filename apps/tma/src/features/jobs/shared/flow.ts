// Переходы мастера S20a–d: шаги — по порядку, «Назад» Telegram — на прошлый экран, а без истории
// (мастер открыли ссылкой или после перезапуска на середине) — на шаг раньше или на Главную.
// Пока в черновике что-то есть, закрытие Mini App спрашивает подтверждение. Правка своей заявки
// (`?edit=<id>`, 5.6) несёт id через все шаги, а с первого шага «Назад» ведёт на S23.
import { color } from '@sosed/design-tokens';
import type { JobDraft } from '@sosed/hooks';
import type { BottomButtonProps } from '@sosed/platform';
import {
  useBackButton,
  useClosingConfirmation,
  useColorScheme,
  useMainButton,
} from '@sosed/platform';
import { useRouter } from '@tanstack/react-router';

import { useDraftStore } from './draft.ts';
import type { CreateStep } from './paths.ts';
import { CREATE_PATHS, CREATE_STEPS, HOME_PATH, managePath } from './paths.ts';

export function useCreateFlow(step: CreateStep, draft: JobDraft | null) {
  const router = useRouter();
  const editing = useDraftStore((state) => state.editing);
  const search = editing ? { edit: editing.jobId } : {};
  const index = CREATE_STEPS.indexOf(step);
  const previous = index > 0 ? CREATE_STEPS[index - 1] : undefined;
  useClosingConfirmation(draft !== null && touched(draft));
  // первый шаг без истории — «Закрыть» Telegram, как на артборде S20a; правка — к своей заявке
  const back = router.history.canGoBack()
    ? () => router.history.back()
    : previous
      ? () => void router.navigate({ to: CREATE_PATHS[previous], search, replace: true })
      : editing
        ? () => void router.navigate({ to: managePath(editing.jobId), replace: true })
        : null;
  useBackButton(back);
  return {
    next() {
      const following = CREATE_STEPS[index + 1];
      if (following) void router.navigate({ to: CREATE_PATHS[following], search });
    },
    open(target: CreateStep) {
      void router.navigate({ to: CREATE_PATHS[target], search });
    },
    home() {
      void router.navigate({ to: HOME_PATH, replace: true });
    },
  };
}

/** В черновике есть ввод человека: его жалко потерять. */
function touched(draft: JobDraft): boolean {
  return draft.title.trim() !== '' || draft.description.trim() !== '' || draft.photos.length > 0;
}

/** MainButton шага в цветах макета (акцент ui.css), а не в цвете кнопки темы Telegram. */
export function useStepButton(
  props: Pick<BottomButtonProps, 'text' | 'onClick' | 'loading' | 'visible' | 'enabled'>,
) {
  const scheme = useColorScheme();
  const palette = color[scheme];
  return useMainButton({ ...props, color: palette.accent, textColor: palette['accent-ink'] });
}
