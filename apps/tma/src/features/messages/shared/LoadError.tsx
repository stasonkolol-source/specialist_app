// Не загрузилось — «Нет соединения» или «Что-то пошло не так» с «Повторить» (как в заявках).
import { systemStateOf } from '@sosed/hooks';
import { useTranslation } from '@sosed/i18n';
import { Button, EmptyState } from '@sosed/ui-web';

export function LoadError({
  error,
  onRetry,
  retrying,
}: {
  error: unknown;
  onRetry: () => void;
  retrying: boolean;
}) {
  const { t: common } = useTranslation();
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
