// Состояние нижней кнопки и подписчики — общее для Telegram, браузера и mock.
import type { BottomButton, BottomButtonState, Unsubscribe } from './types.ts';

export class Listeners<T extends unknown[] = []> {
  private readonly set = new Set<(...args: T) => void>();

  add(listener: (...args: T) => void): Unsubscribe {
    this.set.add(listener);
    return () => {
      this.set.delete(listener);
    };
  }

  emit(...args: T): void {
    for (const listener of [...this.set]) listener(...args);
  }

  get size(): number {
    return this.set.size;
  }
}

export const HIDDEN_BUTTON: BottomButtonState = {
  text: '',
  visible: false,
  enabled: true,
  loading: false,
};

/** Кнопка со state; `apply` передаёт состояние клиенту Telegram (для кнопки в контенте — ничего). */
export function createBottomButton(
  native: boolean,
  apply: (state: BottomButtonState) => void = () => {},
): BottomButton & { press(): void } {
  let state = HIDDEN_BUTTON;
  const changes = new Listeners();
  const clicks = new Listeners();
  return {
    native,
    getState: () => state,
    set(patch) {
      state = { ...state, ...patch };
      apply(state);
      changes.emit();
    },
    subscribe: (listener) => changes.add(listener),
    onClick: (listener) => clicks.add(listener),
    click() {
      if (state.visible && state.enabled && !state.loading) clicks.emit();
    },
    /** Нажатие нативной кнопки: клиент уже проверил видимость и активность. */
    press: () => clicks.emit(),
  };
}
