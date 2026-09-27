// Client-config до маршрутов (DEVELOPMENT_PLAN 1.1, 1.5a): экраны S49 поверх всего приложения.
// Пока конфиг грузится — экран запуска S01 (1.5b).
// По конфигу — «обновите Telegram» (Bot API ниже минимума, !isVersionAtLeast), новая версия
// Mini App, техработы; по ответам API (стор S49) — 426, 503 `maintenance`, санкция на весь
// аккаунт. Конфиг не загрузился из-за сети — S49a с «Повторить»; сбой сервера — пускаем
// (fail open): экраны сами покажут ошибку.
import { NetworkError } from '@sosed/api-client';
import type { SystemState } from '@sosed/hooks';
import { startupState, useClientConfig } from '@sosed/hooks';
import { usePlatform } from '@sosed/platform';
import { useQueryClient } from '@tanstack/react-query';
import type { ReactNode } from 'react';

import { LaunchScreen } from '../features/onboarding/index.ts';
import { SystemScreen, useSystemStore } from '../features/service/s49-system/index.ts';

const OFFLINE: SystemState = { kind: 'offline' };
/** Доля полосы S01, пока грузится конфиг (как на артборде). */
export const CONFIG_PROGRESS = 0.4;

export function StartupGate({ appVersion, children }: { appVersion: string; children: ReactNode }) {
  const platform = usePlatform();
  const queryClient = useQueryClient();
  const config = useClientConfig();
  const forced = useSystemStore((state) => state.appWide);
  const dismiss = useSystemStore((state) => state.dismiss);
  if (config.isPending) return <LaunchScreen progress={CONFIG_PROGRESS} />;
  const telegram = platform.kind === 'browser' ? null : platform.launch.version;
  const state =
    forced ??
    startupState(config.data, { app: appVersion, telegram }) ??
    (config.data === undefined && config.error instanceof NetworkError ? OFFLINE : null);
  if (!state) return children;
  const retry = () => {
    dismiss();
    void queryClient.refetchQueries({ type: 'active' });
  };
  return <SystemScreen state={state} onRetry={retry} retrying={config.isFetching} />;
}
