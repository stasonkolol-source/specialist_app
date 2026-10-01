// Пока черновик и справочники шага грузятся — скелетон; не загрузились — S49a «Нет соединения»
// или «Что-то пошло не так», оба с «Повторить».
import { systemStateOf } from '@sosed/hooks';
import { useTranslation } from '@sosed/i18n';
import { Button, EmptyState, Skeleton, cx } from '@sosed/ui-web';

/** Ширины чипов-скелетонов: ряд похож на категории или районы. */
const CHIP_WIDTHS = ['w-24', 'w-32', 'w-20', 'w-28'] as const;

export function LoadState({
  error,
  onRetry,
  retrying,
}: {
  /** Ошибка загрузки; null — ещё грузится. */
  error: unknown;
  onRetry: () => void;
  retrying: boolean;
}) {
  const { t } = useTranslation('specialist');
  const { t: common } = useTranslation();
  if (error === null) {
    return (
      <div role="status" className="flex flex-col gap-3">
        <span className="sr-only">{t('become.loading')}</span>
        <Skeleton className="h-6 w-1/3" />
        <div className="flex flex-wrap gap-2">
          {CHIP_WIDTHS.map((width) => (
            <Skeleton key={width} radius="round" className={cx('h-10', width)} />
          ))}
        </div>
        <Skeleton className="h-12" />
        <Skeleton className="h-26" />
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
