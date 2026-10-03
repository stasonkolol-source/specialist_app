// Пока черновик и справочники шага грузятся — скелетон по форме экрана (`shape`): поля и чипы
// мастера, строки кабинета и прайса, сетка портфолио; не загрузились — S49a «Нет соединения» или
// «Что-то пошло не так», оба с «Повторить». Фигуры — на поверхности карточек или цвета поверхности
// прямо на фоне экрана: голый .skel на фоне bg2 не виден.
import { systemStateOf } from '@sosed/hooks';
import { useTranslation } from '@sosed/i18n';
import {
  Button,
  ChipSkeleton,
  EmptyState,
  FieldSkeleton,
  RowsSkeleton,
  Skeleton,
  SkeletonCard,
  SkeletonText,
} from '@sosed/ui-web';

/** Ширины чипов-скелетонов: ряд похож на категории или районы. */
const CHIP_WIDTHS = ['w-24', 'w-32', 'w-20', 'w-28'] as const;

/** Форма экрана: мастер и формы (`form`), правка профиля с фото (`edit`), кабинет S33, прайс S35,
 *  портфолио S37 сеткой, работа S37 крупно, доступность S38. */
export type LoadShape =
  'form' | 'edit' | 'cabinet' | 'prices' | 'portfolio' | 'work' | 'availability';

export function LoadState({
  error,
  onRetry,
  retrying,
  shape = 'form',
}: {
  /** Ошибка загрузки; null — ещё грузится. */
  error: unknown;
  onRetry: () => void;
  retrying: boolean;
  shape?: LoadShape;
}) {
  const { t } = useTranslation('specialist');
  const { t: common } = useTranslation();
  if (error === null) {
    return (
      <div role="status" className="flex flex-col gap-3">
        <span className="sr-only">{t('become.loading')}</span>
        <Shape shape={shape} />
      </div>
    );
  }
  const offline = systemStateOf(error).kind === 'offline';
  return (
    <EmptyState
      as="h2"
      size="h2"
      tone="neutral"
      icon={offline ? 'wifi-off' : 'alert'}
      title={common(offline ? 'offline.title' : 'error.title')}
      className="px-6 pt-2"
      action={
        <Button
          variant="secondary"
          icon="refresh"
          onClick={onRetry}
          disabled={retrying}
          aria-busy={retrying}
        >
          {common('action.retry')}
        </Button>
      }
    >
      {common(offline ? 'offline.textEmpty' : 'error.text')}
    </EmptyState>
  );
}

function Shape({ shape }: { shape: LoadShape }) {
  switch (shape) {
    case 'cabinet':
      // карточка профиля со статусом, затем строки разделов кабинета с числами
      return (
        <>
          <SkeletonCard>
            <div className="flex items-center gap-3">
              <Skeleton round className="size-12 shrink-0" />
              <div className="flex min-w-0 grow flex-col">
                <SkeletonText size="title" className="w-1/2" />
                <SkeletonText size="cap" className="w-1/3" />
              </div>
            </div>
            <Skeleton className="h-6 w-28" />
          </SkeletonCard>
          <RowsSkeleton rows={5} leading="icon" subtitle={false} trailing />
        </>
      );
    case 'prices':
      return (
        <>
          <SkeletonText size="cap" screen className="w-1/4" />
          <RowsSkeleton rows={4} leading="none" trailing />
          <Skeleton screen radius="panel" className="h-11 w-full" />
        </>
      );
    case 'portfolio':
      return (
        <>
          <Skeleton screen radius="panel" className="h-11 w-full" />
          <div className="grid grid-cols-3 gap-2">
            {[0, 1, 2, 3, 4, 5].map((tile) => (
              <Skeleton key={tile} screen radius="panel" className="aspect-square w-full" />
            ))}
          </div>
        </>
      );
    case 'work':
      return (
        <>
          <Skeleton screen radius="card" className="aspect-5/6 w-full" />
          <FieldSkeleton tall />
        </>
      );
    case 'availability':
      return (
        <>
          <RowsSkeleton rows={1} leading="none" trailing />
          <div className="flex flex-wrap gap-2">
            {CHIP_WIDTHS.map((width) => (
              <ChipSkeleton key={width} className={width} />
            ))}
          </div>
          <RowsSkeleton rows={1} leading="none" trailing />
        </>
      );
    case 'edit':
      return (
        <>
          <Skeleton round screen className="size-22 self-center" />
          <FieldSkeleton />
          <FieldSkeleton tall />
        </>
      );
    case 'form':
      return (
        <>
          <SkeletonText size="sm" screen className="w-1/3" />
          <div className="flex flex-wrap gap-2">
            {CHIP_WIDTHS.map((width) => (
              <ChipSkeleton key={width} className={width} />
            ))}
          </div>
          <FieldSkeleton />
          <FieldSkeleton tall />
        </>
      );
  }
}
