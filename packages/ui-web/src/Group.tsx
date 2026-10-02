// .group + .row (.row-ic, .grow, .cap, .chev), .num-ic, .dot и .tiles + .tile из ui.css.
import type { MouseEvent, ReactNode } from 'react';

import type { AvatarPalette } from './Avatar.tsx';
import { FOCUS, cx } from './cx.ts';
import type { IconName } from './icon/Icon.tsx';
import { Icon } from './icon/Icon.tsx';

const PALETTE: Record<AvatarPalette, string> = {
  1: 'bg-av1 text-av1-ink',
  2: 'bg-av2 text-av2-ink',
  3: 'bg-av3 text-av3-ink',
  4: 'bg-av4 text-av4-ink',
  5: 'bg-av5 text-av5-ink',
};

/** Иконка строки .row-ic: 36×36, мягкий акцент или палитра категорий; `neutral` — серая
 *  (служебное, S42 «Жалоба рассмотрена»). `large` — 40×40 (плитки), `xl` — 44×44 (карточки
 *  намерения S02b). */
export function RowIcon({
  icon,
  palette,
  neutral = false,
  large = false,
  xl = false,
}: {
  icon: IconName;
  palette?: AvatarPalette;
  neutral?: boolean;
  large?: boolean;
  xl?: boolean;
}) {
  return (
    <span
      aria-hidden="true"
      className={cx(
        'flex shrink-0 items-center justify-center',
        xl ? 'size-11 rounded-btn' : large ? 'size-10 rounded-btn' : 'size-9 rounded-btn-sm',
        neutral
          ? 'bg-bg2 text-text2'
          : palette
            ? PALETTE[palette]
            : 'bg-accent-soft text-accent-soft-ink',
      )}
    >
      <Icon name={icon} />
    </span>
  );
}

/** Отметка «не прочитано» .dot: 8 px, акцент. Подпись обязательна — точка одна ничего не говорит. */
export function UnreadDot({ label }: { label: string }) {
  return (
    <span
      role="img"
      aria-label={label}
      className="inline-block size-2 shrink-0 rounded-full bg-accent"
    />
  );
}

export interface FeedRowProps {
  title: ReactNode;
  /** Текст под заголовком: до трёх строк (.sm .t2). */
  children: ReactNode;
  /** Иконка слева (RowIcon с палитрой) или свой элемент. */
  leading: ReactNode;
  /** Справа от заголовка: время, отметка «не прочитано». */
  meta?: ReactNode;
  href?: string;
  onClick?: (event: MouseEvent<HTMLElement>) => void;
}

/** Строка ленты (.row, align-items: flex-start): заголовок жирным, справа — время, под ним — текст.
 *  С `href` — ссылка (переход внутри приложения делает `onClick`), без — статичная строка. */
export function FeedRow({ title, children, leading, meta, href, onClick }: FeedRowProps) {
  const classes = cx(
    'flex w-full items-start gap-3 border-0 border-b border-line bg-transparent px-4 py-3 text-left text-text no-underline last:border-b-0',
    href && FOCUS,
  );
  const content = (
    <>
      {leading}
      <span className="flex min-w-0 flex-1 flex-col gap-0.5">
        <span className="flex items-start justify-between gap-2">
          <span className="text-body font-semibold">{title}</span>
          {meta && (
            <span className="flex shrink-0 items-center gap-1.5 pt-0.5 text-cap text-text2">
              {meta}
            </span>
          )}
        </span>
        <span className="text-sm text-text2">{children}</span>
      </span>
    </>
  );
  return href ? (
    <a href={href} onClick={onClick} className={classes}>
      {content}
    </a>
  ) : (
    <div className={classes}>{content}</div>
  );
}

/** Номер пункта .num-ic: круг 28 px, мягкий акцент (правила S02c, S48). */
export function NumIcon({ children }: { children: ReactNode }) {
  return (
    <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-accent-soft text-sm leading-7 font-bold text-accent-soft-ink">
      {children}
    </span>
  );
}

export function Group({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cx('overflow-hidden rounded-card bg-surface', className)}>{children}</div>;
}

export interface RowProps {
  title: ReactNode;
  subtitle?: ReactNode;
  icon?: IconName;
  /** Аватар или другой элемент слева вместо иконки. */
  leading?: ReactNode;
  /** Бейдж, переключатель, значение справа. */
  trailing?: ReactNode;
  /** Стрелка «перейти» справа. */
  chevron?: boolean;
  href?: string;
  /** С `href` — переход внутри приложения (роутер отменяет переход браузера), без — кнопка. */
  onClick?: (event: MouseEvent<HTMLElement>) => void;
  /** Строка-раскрывашка (дерево категорий S04): aria-expanded и стрелка вниз или вверх. */
  expanded?: boolean;
  /** Вложенная строка: отступ под иконку родителя (подкатегории S04). */
  inset?: boolean;
}

export function Row({
  title,
  subtitle,
  icon,
  leading,
  trailing,
  chevron = false,
  href,
  onClick,
  expanded,
  inset = false,
}: RowProps) {
  const classes = cx(
    'flex min-h-13 w-full items-center gap-3 border-0 border-b border-line bg-transparent py-3 pr-4 text-left text-text last:border-b-0',
    inset ? 'pl-16' : 'pl-4',
    (href || onClick) && FOCUS,
  );
  const content = (
    <>
      {icon ? <RowIcon icon={icon} /> : leading}
      <span className="flex min-w-0 flex-1 flex-col">
        <span className="text-body">{title}</span>
        {subtitle && <span className="text-cap text-text2">{subtitle}</span>}
      </span>
      {trailing}
      {chevron && <Icon name="chev-right" className="text-text2" />}
      {expanded !== undefined && (
        <Icon name="chev-down" className={cx('text-text2', expanded && 'rotate-180')} />
      )}
    </>
  );
  if (href) {
    return (
      <a href={href} onClick={onClick} className={classes}>
        {content}
      </a>
    );
  }
  if (onClick) {
    return (
      <button type="button" onClick={onClick} aria-expanded={expanded} className={classes}>
        {content}
      </button>
    );
  }
  return <div className={classes}>{content}</div>;
}

/** Сетка категорий в три колонки. */
export function Tiles({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cx('grid grid-cols-3 gap-2', className)}>{children}</div>;
}

export function Tile({
  label,
  icon,
  palette,
  neutral = false,
  href,
  onClick,
}: {
  label: string;
  icon: IconName;
  palette?: AvatarPalette;
  /** Серая иконка: «Все услуги» среди категорий (S03). */
  neutral?: boolean;
  href?: string;
  /** С `href` — переход внутри приложения (роутер отменяет переход браузера), без — кнопка. */
  onClick?: (event: MouseEvent<HTMLElement>) => void;
}) {
  const classes = cx(
    'flex min-h-24 w-full flex-col justify-between gap-2 rounded-card border-0 bg-surface p-3 text-left text-tile text-text',
    FOCUS,
  );
  const content = (
    <>
      <RowIcon icon={icon} palette={palette} neutral={neutral} large />
      {label}
    </>
  );
  return href ? (
    <a href={href} onClick={onClick} className={classes}>
      {content}
    </a>
  ) : (
    <button type="button" onClick={onClick} className={classes}>
      {content}
    </button>
  );
}
