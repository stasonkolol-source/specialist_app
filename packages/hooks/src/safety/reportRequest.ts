// Шторка жалобы S46 открывается с любого экрана (S08, S11, S15, S30), а живёт в одном месте —
// у точки сборки приложения: экран говорит, на что жалоба, точка сборки рисует шторку своим
// чанком. Состояние — одно на приложение, без DOM: его же прочитает мобильное приложение.
import type { ReportTargetType } from './reports.ts';
import { useSyncExternalStore } from 'react';

export interface ReportTarget {
  type: ReportTargetType;
  id: string;
  /** Чей объект — для «Также заблокировать» (профиль, собеседник); нет — галочки нет. */
  userId?: string;
  /** Имя или название — подзаголовок шторки и строка S44 после блокировки. */
  name?: string;
  /** Профиль специалиста — убрать его из загруженной выдачи сразу после блокировки. */
  profileId?: string;
  /** Диалог, где всё случилось (меню чата S30): модератор прочитает переписку. */
  conversationId?: string;
}

let current: ReportTarget | null = null;
const listeners = new Set<() => void>();

function emit() {
  for (const listener of [...listeners]) listener();
}

export function openReport(target: ReportTarget) {
  current = target;
  emit();
}

export function closeReport() {
  if (current === null) return;
  current = null;
  emit();
}

const subscribe = (listener: () => void) => {
  listeners.add(listener);
  return () => void listeners.delete(listener);
};
const snapshot = () => current;

/** На что сейчас открыта шторка жалобы; null — закрыта. Экраны прячут свою MainButton, пока
 *  она открыта: кнопка Telegram под затемнением осталась бы нажимаемой. */
export function useReportTarget(): ReportTarget | null {
  return useSyncExternalStore(subscribe, snapshot, snapshot);
}
