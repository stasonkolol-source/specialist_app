/** Склейка классов без пустых значений. */
export function cx(...classes: (string | false | null | undefined)[]): string {
  return classes.filter(Boolean).join(' ');
}

/** Видимый фокус с клавиатуры для всех интерактивных элементов. */
export const FOCUS =
  'outline-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent';

// Отклик на нажатие — только CSS: системную подсветку WebView убирает styles.css, вместо неё элемент
// чуть сжимается. Отключённый не сжимается; при prefers-reduced-motion — без движения.
/** Кнопка, чип, плитка, вариант. */
export const PRESS =
  'motion-safe:transition-transform motion-safe:duration-100 motion-safe:active:not-disabled:scale-[0.97]';
/** Карточка-ссылка: крупное сжимается меньше. */
export const PRESS_CARD =
  'motion-safe:transition-transform motion-safe:duration-100 motion-safe:active:scale-[0.99]';
/** Строка списка: подсветка фоном bg2 — видна на поверхности группы и на фоне шторки в обеих темах. */
export const PRESS_ROW = 'transition-colors duration-100 active:not-disabled:bg-bg2';
