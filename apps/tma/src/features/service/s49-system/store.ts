// Системные состояния S49, которые пришли не с экрана, а из ответа API (DEVELOPMENT_PLAN 1.5a).
// Точка сборки (app/) кладёт сюда ошибки запросов, экраны S49 читают:
// - `appWide` — закрывает всё приложение: 426 (обновить Mini App), 503 `maintenance`, санкция на
//   весь аккаунт (suspended, banned — ещё при входе);
// - `restriction` — частичная санкция последнего действия (403 `restricted`): экран S49b.
import type { SystemState } from '@sosed/hooks';
import { isAppWide, systemStateOf } from '@sosed/hooks';
import { create } from 'zustand';

export type RestrictedState = Extract<SystemState, { kind: 'restricted' }>;

interface SystemStore {
  appWide: SystemState | null;
  restriction: RestrictedState | null;
  /** «Повторить» на экране поверх приложения: состояние снова решат ответы сервера. */
  dismiss: () => void;
}

export const useSystemStore = create<SystemStore>((set) => ({
  appWide: null,
  restriction: null,
  dismiss: () => set({ appWide: null }),
}));

/** Ошибка запроса → состояние S49. `true` — частичная санкция: пора открыть экран S49b. */
export function reportSystemError(error: unknown): boolean {
  const state = systemStateOf(error);
  if (isAppWide(state)) {
    useSystemStore.setState({ appWide: state });
    return false;
  }
  if (state.kind === 'restricted') {
    useSystemStore.setState({ restriction: state });
    return true;
  }
  return false;
}
