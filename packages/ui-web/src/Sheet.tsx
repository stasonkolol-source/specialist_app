// .scrim + .sheet + .grab: шторка снизу (фильтры S06). Модальный диалог: фокус не уходит под
// шторку (Tab и Shift+Tab по кругу), Escape и тап по затемнению закрывают, после закрытия фокус
// возвращается туда, откуда шторку открыли. Кнопку «Назад» Telegram подключает экран
// (@sosed/platform, useBackButton) — компонент о Telegram не знает.
import type { KeyboardEvent, ReactNode } from 'react';
import { useEffect, useId, useRef } from 'react';

import { IconButton } from './Button.tsx';
import { Heading } from './text/Heading.tsx';

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

export interface SheetProps {
  open: boolean;
  title: string;
  onClose: () => void;
  /** Подпись кнопки-крестика: у неё нет текста. */
  closeLabel: string;
  /** false — без крестика: у шторки уже есть своя отмена («Отмена» S25, «Не сейчас» S54), второй
   *  выход только спорил бы с ней. Escape и тап по затемнению закрывают по-прежнему. */
  closeButton?: boolean;
  children: ReactNode;
  /** Кнопки внизу шторки (в браузере — вместо MainButton Telegram). */
  footer?: ReactNode;
}

export function Sheet({
  open,
  title,
  onClose,
  closeLabel,
  closeButton = true,
  children,
  footer,
}: SheetProps) {
  const titleId = useId();
  const dialog = useRef<HTMLElement>(null);

  useEffect(() => {
    if (!open) return undefined;
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    // шторка ещё въезжает снизу: фокус без прокрутки к ней
    dialog.current?.focus({ preventScroll: true });
    return () => opener?.focus();
  }, [open]);

  if (!open) return null;

  const onKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    if (event.key === 'Escape') {
      event.stopPropagation();
      onClose();
      return;
    }
    if (event.key !== 'Tab' || !dialog.current) return;
    const focusable = [...dialog.current.querySelectorAll<HTMLElement>(FOCUSABLE)];
    const first = focusable[0];
    const last = focusable.at(-1);
    if (!first || !last) {
      event.preventDefault();
      return;
    }
    const active = document.activeElement;
    if (event.shiftKey && (active === first || active === dialog.current)) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && active === last) {
      event.preventDefault();
      first.focus();
    }
  };

  return (
    // шторка — flex-элемент у нижнего края: длинное содержимое сжимает её до отступа сверху
    // (затемнение остаётся видно) и прокручивается внутри
    <div className="fixed inset-0 z-40 flex flex-col justify-end">
      {/* появление: затемнение проявляется, шторка въезжает снизу; без анимации при reduced motion */}
      <div
        className="absolute inset-0 bg-scrim motion-safe:animate-fade-in"
        aria-hidden="true"
        onClick={onClose}
      />
      <section
        ref={dialog}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        onKeyDown={onKeyDown}
        // *:shrink-0 — в колонке с прокруткой flex сжал бы группы (overflow-hidden) вместо прокрутки
        className="relative mt-12 flex min-h-0 flex-col gap-4 overflow-y-auto rounded-t-sheet bg-bg px-4 pt-2 pb-8 outline-none *:shrink-0 motion-safe:animate-sheet-in"
      >
        <div className="mx-auto h-1.25 w-9 shrink-0 rounded-full bg-line" aria-hidden="true" />
        {/* высота строки — как с крестиком (44): без него заголовок не прыгает */}
        <div className="flex min-h-11 items-center justify-between gap-2">
          <Heading variant="h2" as="h2" id={titleId}>
            {title}
          </Heading>
          {closeButton && <IconButton icon="x" label={closeLabel} onClick={onClose} />}
        </div>
        {children}
        {footer}
      </section>
    </div>
  );
}
