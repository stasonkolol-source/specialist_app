// .card / .card.tight: поверхность, радиус 16, отступ 16. Ссылка или кнопка — вся карточка кликабельна.
import type { ReactNode } from 'react';

import { FOCUS, cx } from './cx.ts';

export interface CardProps {
  children: ReactNode;
  tight?: boolean;
  href?: string;
  onClick?: () => void;
  /** ul / ol — карточка-список (.card у пунктов правил S48, «Остаётся доступно» S49b). */
  as?: 'div' | 'section' | 'article' | 'li' | 'ul' | 'ol';
  className?: string;
}

export function Card({
  children,
  tight = false,
  href,
  onClick,
  as: Tag = 'div',
  className,
}: CardProps) {
  const classes = cx(
    'm-0 flex list-none flex-col rounded-card bg-surface p-4 text-text',
    tight ? 'gap-2' : 'gap-3',
    (href || onClick) && cx('cursor-pointer', FOCUS),
    className,
  );
  if (href) {
    return (
      <a href={href} className={cx(classes, 'text-text')}>
        {children}
      </a>
    );
  }
  if (onClick) {
    return (
      <button type="button" onClick={onClick} className={cx(classes, 'w-full border-0 text-left')}>
        {children}
      </button>
    );
  }
  return <Tag className={classes}>{children}</Tag>;
}
