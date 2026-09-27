// Последний рубеж: необработанная ошибка рендера — экран S49 с повтором, а не белый экран. Сюда же
// приходят ошибки экранов (у роутера нет своего запасного экрана): чанк вкладки не скачался без
// сети — S49a «Нет соединения», прочее — «Что-то пошло не так». Ошибки API экраны обрабатывают
// сами (ApiError, S49).
import type { SystemState } from '@sosed/hooks';
import { systemStateOf } from '@sosed/hooks';
import type { ErrorInfo, ReactNode } from 'react';
import { Component } from 'react';

import { SystemScreen } from '../features/service/s49-system/index.ts';

interface Props {
  children: ReactNode;
  /** «Повторить»: загрузить заново то, что упало (чанки экранов, маршруты), прежде чем рисовать. */
  onReset?: () => Promise<void>;
  onError?: (error: unknown, info: ErrorInfo) => void;
}

interface State {
  failed: SystemState | null;
  retrying: boolean;
}

export class ErrorBoundary extends Component<Props, State> {
  override state: State = { failed: null, retrying: false };

  static getDerivedStateFromError(error: unknown): Partial<State> {
    return { failed: systemStateOf(error) };
  }

  override componentDidCatch(error: unknown, info: ErrorInfo): void {
    this.props.onError?.(error, info);
  }

  private readonly retry = async () => {
    this.setState({ retrying: true });
    try {
      await this.props.onReset?.();
    } finally {
      this.setState({ failed: null, retrying: false });
    }
  };

  override render(): ReactNode {
    const { failed, retrying } = this.state;
    if (!failed) return this.props.children;
    return <SystemScreen state={failed} onRetry={() => void this.retry()} retrying={retrying} />;
  }
}
