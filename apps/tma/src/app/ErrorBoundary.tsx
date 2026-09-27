// Последний рубеж: необработанная ошибка рендера — экран S49 «что-то пошло не так» с повтором,
// а не белый экран. Ошибки API экраны обрабатывают сами (ApiError, S49).
import type { ErrorInfo, ReactNode } from 'react';
import { Component } from 'react';

import { SystemScreen } from '../features/service/s49-system/index.ts';

const ERROR = { kind: 'error', traceId: null } as const;

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
    return <SystemScreen state={ERROR} onRetry={() => this.setState({ failed: false })} />;
  }
}
