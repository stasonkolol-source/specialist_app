// Переходы мастера S20a–d: весь мастер — одна запись истории, шаги заменяют друг друга. «Назад»
// Telegram — на шаг раньше, с первого шага — туда, откуда мастер открыли (без истории — «Закрыть»
// Telegram). Отправленный мастер так не оставляет в истории своих шагов: S21 заменяет его запись, и
// «Назад» с S21 и S23 ведёт туда, откуда начали, а не в пустые шаги (OWN-2). Пока в черновике
// что-то есть, закрытие Mini App спрашивает подтверждение. Правка своей заявки (`?edit=<id>`, 5.6)
// заменяет запись S23 и несёт id через все шаги, а с первого шага «Назад» — снова S23.
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
  const back = previous
    ? () => void router.navigate({ to: CREATE_PATHS[previous], search, replace: true })
    : editing
      ? () => void router.navigate({ to: managePath(editing.jobId), replace: true })
      : router.history.canGoBack()
        ? () => router.history.back()
        : null;
  useBackButton(back);
  return {
    next() {
      const following = CREATE_STEPS[index + 1];
      if (following) void router.navigate({ to: CREATE_PATHS[following], search, replace: true });
    },
    open(target: CreateStep) {
      void router.navigate({ to: CREATE_PATHS[target], search, replace: true });
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
