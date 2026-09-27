// .stack / .hstack / .between из ui.css.
import type { ReactNode } from 'react';

import { cx } from '../cx.ts';

export type Gap = 4 | 8 | 12 | 16 | 24;

const GAP: Record<Gap, string> = { 4: 'gap-1', 8: 'gap-2', 12: 'gap-3', 16: 'gap-4', 24: 'gap-6' };

type Tag = 'div' | 'section' | 'ul' | 'ol' | 'main' | 'header' | 'footer';

interface BaseProps {
  children?: ReactNode;
  as?: Tag;
  className?: string;
}

/** Вертикальная стопка, по умолчанию gap 16. */
export function Stack({
  children,
  as: As = 'div',
  gap = 16,
  className,
}: BaseProps & { gap?: Gap }) {
  return <As className={cx('flex flex-col', GAP[gap], className)}>{children}</As>;
}

/** Горизонтальный ряд по центру, по умолчанию gap 8; `between` — края врозь, gap 12. */
export function HStack({
  children,
  as: As = 'div',
  gap,
  wrap = false,
  between = false,
  className,
}: BaseProps & { gap?: Gap; wrap?: boolean; between?: boolean }) {
  return (
    <As
      className={cx(
        'flex items-center',
        GAP[gap ?? (between ? 12 : 8)],
        wrap && 'flex-wrap',
        between && 'justify-between',
        className,
      )}
    >
      {children}
    </As>
  );
}
