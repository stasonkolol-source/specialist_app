// Последний рубеж: необработанная ошибка рендера — экран «что-то пошло не так» с повтором,
// а не белый экран. Ошибки API экраны обрабатывают сами (ApiError, S49).
import { useTranslation } from '@sosed/i18n';
import { Button, EmptyState } from '@sosed/ui-web';
import type { ErrorInfo, ReactNode } from 'react';
import { Component } from 'react';

interface Props {
  children: ReactNode;
  onError?: (error: unknown, info: ErrorInfo) => void;
}

interface State {
  failed: boolean;
}

export class ErrorBoundary extends Component<Props, State> {
  override state: State = { failed: false };

  static getDerivedStateFromError(): State {
    return { failed: true };
  }

  override componentDidCatch(error: unknown, info: ErrorInfo): void {
    this.props.onError?.(error, info);
  }

  override render(): ReactNode {
    if (!this.state.failed) return this.props.children;
    return <Fallback onRetry={() => this.setState({ failed: false })} />;
  }
}

function Fallback({ onRetry }: { onRetry: () => void }) {
  const { t } = useTranslation();
  return (
    <div className="flex min-h-dvh items-center justify-center bg-bg2">
      <EmptyState
        icon="alert"
        title={t('error.title')}
        action={
          <Button variant="secondary" onClick={onRetry}>
            {t('action.retry')}
          </Button>
        }
      >
        {t('error.text')}
      </EmptyState>
    </div>
  );
}
