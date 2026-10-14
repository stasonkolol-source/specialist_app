// Шторка «Что проверено» открывается с нескольких экранов (бейдж «Проверен модератором» и
// «Приглашён командой» на S08, «Как мы проверяем» на S08, S11 и S24), а живёт в одном месте — у
// точки сборки приложения, как шторка жалобы (reportRequest.ts): экран говорит, о чём она, точка
// сборки рисует её своим чанком. ZZP 35/2026 ст. 19–20: бейдж называет факт, расшифровка — в один
// тап. Состояние — одно на приложение, без DOM.
import { useSyncExternalStore } from 'react';

export interface CheckedTarget {
  /** moderated — что именно проверил модератор; founding — кто такой «приглашён командой». */
  kind: 'moderated' | 'founding';
  /** Когда модератор проверил профиль (published_at); нет — текст без даты. */
  checkedAt: string | null;
}

let current: CheckedTarget | null = null;
const listeners = new Set<() => void>();

function emit() {
  for (const listener of [...listeners]) listener();
}

export function openChecked(target: CheckedTarget) {
  current = target;
  emit();
}

export function closeChecked() {
  if (current === null) return;
  current = null;
  emit();
}

const subscribe = (listener: () => void) => {
  listeners.add(listener);
  return () => void listeners.delete(listener);
};
const snapshot = () => current;

/** О чём сейчас открыта шторка «Что проверено»; null — закрыта. Экраны прячут свою MainButton,
 *  пока она открыта: кнопка Telegram под затемнением осталась бы нажимаемой. */
export function useCheckedTarget(): CheckedTarget | null {
  return useSyncExternalStore(subscribe, snapshot, snapshot);
}
