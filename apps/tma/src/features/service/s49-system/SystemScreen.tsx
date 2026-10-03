// S49 поверх всего приложения (DEVELOPMENT_PLAN 1.5a): нет сети при старте (S49a), ошибка,
// техработы, «обновите Telegram» / новая версия Mini App и санкция на весь аккаунт (S49b).
// Навигации нет: в шапке Telegram — «Закрыть». Состояния экрана (нет сети на вкладке) рисует
// сам экран тем же EmptyState.
import type { SystemState } from '@sosed/hooks';
import { useTranslation } from '@sosed/i18n';
import { useInsets } from '@sosed/platform';
import { Button, EmptyState } from '@sosed/ui-web';
import type { ReactNode } from 'react';
import { Suspense, lazy } from 'react';

// S49b — только ответом сервера (санкция), сеть в этот момент есть: экран с правилами площадки
// грузится своим чанком, а не лежит в первом. Нет сети, техработы и ошибка — здесь, без загрузки
const RestrictedScreen = lazy(() =>
  import('./RestrictedScreen.tsx').then((module) => ({ default: module.RestrictedScreen })),
);

export interface SystemScreenProps {
  state: SystemState;
  /** «Повторить»: перечитать конфигурацию или перерисовать приложение. */
  onRetry: () => void;
  /** Повтор уже идёт: кнопка недоступна, пока не придёт ответ. */
  retrying?: boolean;
}

export function SystemScreen({ state, onRetry, retrying = false }: SystemScreenProps) {
  if (state.kind === 'restricted') {
    return (
      <Frame>
        <Suspense fallback={null}>
          <RestrictedScreen state={state} />
        </Suspense>
      </Frame>
    );
  }
  return (
    <Frame center>
      <Notice state={state} onRetry={onRetry} retrying={retrying} />
    </Frame>
  );
}

function Notice({
  state,
  onRetry,
  retrying,
}: {
  state: Exclude<SystemState, { kind: 'restricted' }>;
  onRetry: () => void;
  retrying: boolean;
}) {
  const { t } = useTranslation();
  const retry = (
    <Button
      variant="secondary"
      icon="refresh"
      onClick={onRetry}
      disabled={retrying}
      aria-busy={retrying}
    >
      {t('action.retry')}
    </Button>
  );
  switch (state.kind) {
    case 'offline':
      return (
        <EmptyState
          as="h1"
          size="h2"
          tone="neutral"
          icon="wifi-off"
          title={t('offline.title')}
          action={retry}
        >
          {t('offline.textEmpty')}
        </EmptyState>
      );
    case 'maintenance':
      return (
        <EmptyState as="h1" size="h2" icon="settings" title={t('maintenance.title')} action={retry}>
          {t('maintenance.text')}
        </EmptyState>
      );
    case 'update':
      return state.target === 'telegram' ? (
        <EmptyState as="h1" size="h2" icon="alert" title={t('update.telegramTitle')}>
          {t('update.telegramText')}
        </EmptyState>
      ) : (
        <EmptyState
          as="h1"
          size="h2"
          icon="refresh"
          title={t('update.appTitle')}
          action={<Button onClick={() => window.location.reload()}>{t('update.reload')}</Button>}
        >
          {t('update.appText')}
        </EmptyState>
      );
    case 'error':
      return (
        <EmptyState as="h1" size="h2" icon="alert" title={t('error.title')} action={retry}>
          {t('error.text')}
        </EmptyState>
      );
  }
}

function Frame({ center = false, children }: { center?: boolean; children: ReactNode }) {
  const insets = useInsets();
  return (
    <main
      className={
        center
          ? 'mx-auto flex min-h-dvh max-w-lg flex-col justify-center bg-bg2'
          : 'mx-auto flex min-h-dvh max-w-lg flex-col bg-bg2'
      }
      style={{
        paddingTop: insets.top,
        paddingRight: insets.right,
        paddingBottom: insets.bottom,
        paddingLeft: insets.left,
      }}
    >
      {children}
    </main>
  );
}
