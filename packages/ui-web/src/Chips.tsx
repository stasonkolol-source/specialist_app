// .chips / .chips.wrap + .chip / .chip.on / .chip.acc / .chip .n; .avs + .ava.xs; .price / .price.lg.
import type { ReactNode } from 'react';

import type { AvatarPalette } from './Avatar.tsx';
import { Avatar } from './Avatar.tsx';
import { FOCUS, cx } from './cx.ts';
import type { IconName } from './icon/Icon.tsx';
import { Icon } from './icon/Icon.tsx';

export function Chips({
  children,
  wrap = false,
  label,
  className,
}: {
  children: ReactNode;
  wrap?: boolean;
  /** Подпись группы фильтров для скринридера. */
  label?: string;
  className?: string;
}) {
  return (
    <div
      role={label ? 'group' : undefined}
      aria-label={label}
      className={cx('flex gap-2', wrap ? 'flex-wrap' : 'overflow-x-auto', className)}
    >
      {children}
    </div>
  );
}

export interface ChipProps {
  children: ReactNode;
  /** .chip.on — выбранный фильтр. */
  selected?: boolean;
  /** .chip.acc — акцентный (подсказка, быстрый фильтр). */
  accent?: boolean;
  icon?: IconName;
  /** Счётчик .n справа. */
  count?: number;
  onClick?: () => void;
  href?: string;
}

export function Chip({
  children,
  selected = false,
  accent = false,
  icon,
  count,
  onClick,
  href,
}: ChipProps) {
  const classes = cx(
    'inline-flex h-10 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-chip border px-3.5 text-sm font-medium',
    selected
      ? 'border-text bg-text text-bg'
      : accent
        ? 'border-transparent bg-accent-soft text-accent-soft-ink'
        : 'border-line bg-surface text-text',
    FOCUS,
  );
  const content = (
    <>
      {icon && <Icon name={icon} size={16} />}
      {children}
      {count !== undefined && (
        <span className="h-5 min-w-5 rounded-full bg-accent px-1.5 text-center text-badge leading-5 font-bold text-accent-ink">
          {count}
        </span>
      )}
    </>
  );
  if (href) {
    return (
      <a href={href} className={classes} aria-current={selected ? 'true' : undefined}>
        {content}
      </a>
    );
  }
  return (
    <button type="button" onClick={onClick} aria-pressed={selected} className={classes}>
      {content}
    </button>
  );
}

/** Стопка аватаров .avs: по умолчанию xs, каждый следующий заходит на предыдущий на 8 px. */
export function AvatarStack({
  people,
  label,
  className,
}: {
  people: { name: string; palette?: AvatarPalette; src?: string }[];
  /** Подпись стопки («Откликнулись 3 специалиста»). */
  label: string;
  className?: string;
}) {
  return (
    <div role="group" aria-label={label} className={cx('flex', className)}>
      {people.map((p, i) => (
        <Avatar
          key={`${p.name}-${i}`}
          name={p.name}
          palette={p.palette}
          src={p.src}
          size="xs"
          stacked
          className={i > 0 ? '-ml-2' : undefined}
        />
      ))}
    </div>
  );
}

/** Цена: уже отформатированная строка (useFormat().price) — компонент только оформляет. */
export function Price({
  children,
  large = false,
  className,
}: {
  children: ReactNode;
  large?: boolean;
  className?: string;
}) {
  return (
    <span
      className={cx(
        'whitespace-nowrap tabular-nums',
        large ? 'text-price-lg' : 'text-price',
        className,
      )}
    >
      {children}
    </span>
  );
}
