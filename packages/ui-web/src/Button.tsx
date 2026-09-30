// .btn pri/sec/out/dng, .btn.sm, .btn.full и .ibtn из ui.css.
import type { ButtonHTMLAttributes, ReactNode } from 'react';

import { FOCUS, cx } from './cx.ts';
import type { IconName } from './icon/Icon.tsx';
import { Icon } from './icon/Icon.tsx';

export type ButtonVariant = 'primary' | 'secondary' | 'outline' | 'danger';

const VARIANT: Record<ButtonVariant, string> = {
  primary: 'bg-accent text-accent-ink',
  secondary: 'bg-accent-soft text-accent-soft-ink',
  outline: 'border border-line bg-surface text-text',
  danger: 'bg-danger-soft text-danger',
};

export interface ButtonProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'children'> {
  children: ReactNode;
  variant?: ButtonVariant;
  /** 36 px — только вторичные действия внутри карточек. */
  size?: 'md' | 'sm';
  full?: boolean;
  icon?: IconName;
  /** Ссылка вместо кнопки (.btn как <a>). */
  href?: string;
}

export function Button({
  children,
  variant = 'primary',
  size = 'md',
  full = false,
  icon,
  href,
  className,
  type = 'button',
  ...rest
}: ButtonProps) {
  const classes = cx(
    'inline-flex items-center justify-center gap-2 whitespace-nowrap border-0 text-button',
    size === 'md' ? 'h-11 rounded-btn px-4' : 'h-9 rounded-btn-sm px-3 text-sm font-semibold',
    VARIANT[variant],
    full && 'w-full',
    'disabled:bg-bg2 disabled:text-text2',
    FOCUS,
    className,
  );
  const content = (
    <>
      {icon && <Icon name={icon} size={size === 'md' ? 20 : 16} />}
      {children}
    </>
  );
  if (href) {
    return (
      <a href={href} className={classes}>
        {content}
      </a>
    );
  }
  return (
    <button type={type} className={classes} {...rest}>
      {content}
    </button>
  );
}

/** Текстовая кнопка .link.sm: действие рядом с заголовком («Прочитать все» S42), зона нажатия
 *  не меньше 44 px по высоте. */
export function LinkButton({
  children,
  className,
  type = 'button',
  ...rest
}: Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'children'> & { children: ReactNode }) {
  return (
    <button
      type={type}
      className={cx(
        'inline-flex min-h-11 items-center border-0 bg-transparent px-2 text-sm font-semibold text-accent disabled:text-text2',
        FOCUS,
        className,
      )}
      {...rest}
    >
      {children}
    </button>
  );
}

export interface IconButtonProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'children'> {
  icon: IconName;
  /** Обязательная подпись: у кнопки нет текста. */
  label: string;
  /** .ibtn.plain — без подложки. */
  plain?: boolean;
  /** .ibtn.on — активное состояние (например, «в избранном»). */
  active?: boolean;
}

export function IconButton({
  icon,
  label,
  plain = false,
  active = false,
  className,
  type = 'button',
  ...rest
}: IconButtonProps) {
  return (
    <button
      type={type}
      aria-label={label}
      {...(active ? { 'aria-pressed': true } : {})}
      className={cx(
        'inline-flex size-11 shrink-0 items-center justify-center rounded-btn border-0',
        plain ? 'bg-transparent' : 'bg-bg2',
        active ? 'text-danger' : 'text-text',
        FOCUS,
        className,
      )}
      {...rest}
    >
      <Icon name={icon} />
    </button>
  );
}
