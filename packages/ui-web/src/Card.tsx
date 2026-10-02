// .card / .card.tight: поверхность, радиус 16, отступ 16. Ссылка или кнопка — вся карточка кликабельна.
import type { MouseEvent, ReactNode } from 'react';

import { FOCUS, cx } from './cx.ts';

export interface CardProps {
  children: ReactNode;
  tight?: boolean;
  href?: string;
  /** С `href` — переход внутри приложения (роутер отменяет переход браузера), без — кнопка. */
  onClick?: (event: MouseEvent<HTMLElement>) => void;
  /** ul / ol — карточка-список (.card у пунктов правил S48, «Остаётся доступно» S49b). */
  as?: 'div' | 'section' | 'article' | 'li' | 'ul' | 'ol';
  className?: string;
  /** Подпись раздела-карточки (`as="section"`): заголовок внутри или текст для скринридера. */
  'aria-labelledby'?: string;
  'aria-label'?: string;
}

export function Card({
  children,
  tight = false,
  href,
  onClick,
  as: Tag = 'div',
  className,
  'aria-labelledby': labelledBy,
  'aria-label': label,
}: CardProps) {
  const classes = cx(
    'm-0 flex list-none flex-col rounded-card bg-surface p-4 text-text',
    tight ? 'gap-2' : 'gap-3',
    (href || onClick) && cx('cursor-pointer', FOCUS),
    className,
  );
  if (href) {
    return (
      <a href={href} onClick={onClick} className={cx(classes, 'text-text')}>
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
  return (
    <Tag className={classes} aria-labelledby={labelledBy} aria-label={label}>
      {children}
    </Tag>
  );
}
