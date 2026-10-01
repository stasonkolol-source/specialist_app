// Общее для портфолио S37 и экрана работы (DEVELOPMENT_PLAN 2.11): варианты фото, кэш портфолио и
// удаление работы. Ответы сервера сразу ложатся в кэш: S37 видит правку без перечитывания.
import type { MediaRefOut, PortfolioOut, WorkOut } from '@sosed/api-client';
import { getSpecialistsGetMyPortfolioQueryKey, specialistsRemoveMyWork } from '@sosed/api-client';
import { myProfileQueryKey } from '@sosed/hooks';
import type { PhotoVariant } from '@sosed/ui-web';
import { useMutation, useQueryClient } from '@tanstack/react-query';

/** MAX_CAPTION работы (backend specialists/domain/portfolio.py). */
export const MAX_CAPTION = 120;

/** Варианты готового файла для srcset; пока файл обрабатывается, их нет. */
export function photoVariants(media: MediaRefOut | null): PhotoVariant[] {
  if (media?.status !== 'ready') return [];
  return media.variants.map((variant) => ({ url: variant.url, width: variant.width }));
}

/** Записать работы в кэш портфолио. Сначала — отменить перечитывание, начатое до правки
 *  (опрос, пока файлы обрабатываются): иначе его ответ затёр бы её. */
export function usePortfolioCache() {
  const queryClient = useQueryClient();
  return async (items: (current: WorkOut[]) => WorkOut[]) => {
    const queryKey = getSpecialistsGetMyPortfolioQueryKey();
    await queryClient.cancelQueries({ queryKey });
    queryClient.setQueryData<PortfolioOut>(queryKey, (current) =>
      current ? { ...current, items: items(current.items) } : current,
    );
  };
}

/** Убрать работу: сервер сдвигает остальные на её место — так же и в кэше. */
export function useRemoveWork(onRemoved?: () => void) {
  const queryClient = useQueryClient();
  const cache = usePortfolioCache();
  return useMutation({
    mutationFn: (work: WorkOut) => specialistsRemoveMyWork(work.id),
    onSuccess: async (_, work) => {
      await cache((items) =>
        items
          .filter((item) => item.id !== work.id)
          .map((item, position) => ({ ...item, position })),
      );
      // полнота профиля считает работы — перечитываем
      void queryClient.invalidateQueries({ queryKey: myProfileQueryKey() });
      onRemoved?.();
    },
  });
}
