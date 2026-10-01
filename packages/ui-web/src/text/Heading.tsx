// Типошкала ui.css: .h1 (Unbounded), .h1.xl, .h2, .h3, .sec-t, .cap, .sm, .t2.
import type { ReactNode } from 'react';

import { cx } from '../cx.ts';

export type HeadingVariant = 'h1' | 'h1-xl' | 'h2' | 'h3';

const VARIANT: Record<HeadingVariant, string> = {
  h1: 'font-display text-h1',
  'h1-xl': 'font-display text-h1-xl',
  h2: 'text-h2',
  h3: 'text-h3',
};

type HeadingTag = 'h1' | 'h2' | 'h3' | 'h4';

export interface HeadingProps {
  children: ReactNode;
  /** Крупный заголовок раздела — h1 (Unbounded); внутреннего экрана — h2; секции в карточке — h3. */
  variant?: HeadingVariant;
  as?: HeadingTag;
  className?: string;
}

export function Heading({ children, variant = 'h2', as, className }: HeadingProps) {
  const Tag = as ?? (variant === 'h3' ? 'h2' : 'h1');
  return <Tag className={cx('m-0', VARIANT[variant], className)}>{children}</Tag>;
}

/** Подзаголовок секции снаружи карточек: капсом, вторичный цвет, отступ 16 по бокам. */
export function SectionTitle({
  children,
  as: Tag = 'h2',
  inset = true,
  id,
  className,
}: {
  children: ReactNode;
  as?: HeadingTag;
  inset?: boolean;
  /** Для aria-labelledby секции, которую заголовок называет. */
  id?: string;
  className?: string;
}) {
  return (
    <Tag
      id={id}
      className={cx('m-0 text-section uppercase text-text2', inset && 'px-4', className)}
    >
      {children}
    </Tag>
  );
}

export type TextVariant = 'body' | 'sm' | 'cap' | 'title';

const TEXT: Record<TextVariant, string> = {
  body: 'text-body',
  sm: 'text-sm',
  cap: 'text-cap text-text2',
  title: 'text-title',
};

export function Text({
  children,
  variant = 'body',
  secondary = false,
  bold = false,
  as: Tag = 'p',
  className,
}: {
  children: ReactNode;
  variant?: TextVariant;
  /** .t2 — вторичный цвет. */
  secondary?: boolean;
  /** .b — полужирный. */
  bold?: boolean;
  as?: 'p' | 'span' | 'div';
  className?: string;
}) {
  return (
    <Tag
      className={cx(
        'm-0',
        TEXT[variant],
        secondary && 'text-text2',
        bold && 'font-semibold',
        className,
      )}
    >
      {children}
    </Tag>
  );
}
