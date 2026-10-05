// .steps, .bar, .stars, .bnr, .empty, .toast, .skel из ui.css.
import type { ReactNode } from 'react';

import { FOCUS, cx } from './cx.ts';
import type { IconName } from './icon/Icon.tsx';
import { Icon } from './icon/Icon.tsx';

/** Шаги формы: первые `current` полосок закрашены. */
export function Steps({
  total,
  current,
  label,
}: {
  total: number;
  current: number;
  label: string;
}) {
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={1}
      aria-valuemax={total}
      aria-valuenow={current}
      className="flex gap-1.5"
    >
      {Array.from({ length: total }, (_, i) => (
        <i
          key={i}
          className={cx('h-1 flex-1 rounded-full', i < current ? 'bg-accent' : 'bg-line')}
        />
      ))}
    </div>
  );
}

/** Полоса прогресса .bar: value от 0 до max. */
export function ProgressBar({
  value,
  max = 100,
  label,
}: {
  value: number;
  max?: number;
  label: string;
}) {
  const pct = Math.max(0, Math.min(100, (value / max) * 100));
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={max}
      aria-valuenow={value}
      className="h-2 overflow-hidden rounded-full bg-line"
    >
      {/* ширина — раскладка, не цвет: inline-стиль допустим */}
      <i className="block h-full rounded-full bg-accent" style={{ width: `${pct}%` }} />
    </div>
  );
}

/** Оценка звёздами .stars: без onChange — только показ. Пустая звезда для показа — цвет рамки поля
 *  (3,2:1: «4» и «5» различимы), при выставлении оценки — контур цвета text2: пять звёзд видны до
 *  первого нажатия (с цветом line их было почти не видно, 1,14:1). */
export function Stars({
  value,
  onChange,
  label,
  starLabel,
}: {
  value: number;
  onChange?: (value: number) => void;
  label: string;
  /** Подпись звезды для скринридера: (n) => t('rating.star', { count: n }). */
  starLabel: (n: number) => string;
}) {
  const stars = [1, 2, 3, 4, 5];
  if (!onChange) {
    return (
      <div role="img" aria-label={label} className="flex gap-1">
        {stars.map((n) => (
          <Icon key={n} name="star" size={16} className={n <= value ? 'text-star' : 'text-field'} />
        ))}
      </div>
    );
  }
  return (
    <div role="radiogroup" aria-label={label} className="flex gap-1">
      {stars.map((n) => (
        <button
          key={n}
          type="button"
          role="radio"
          aria-checked={n === value}
          aria-label={starLabel(n)}
          onClick={() => onChange(n)}
          className={cx(
            'flex size-12 items-center justify-center border-0 bg-transparent p-0',
            n <= value ? 'text-star' : 'text-text2',
            FOCUS,
          )}
        >
          <Icon name={n <= value ? 'star' : 'star-outline'} size={36} />
        </button>
      ))}
    </div>
  );
}

export type BannerTone = 'warn' | 'ok' | 'info' | 'danger';

const BANNER: Record<BannerTone, string> = {
  warn: 'bg-urgent-soft text-urgent-soft-ink',
  ok: 'bg-accent-soft text-accent-soft-ink',
  info: 'bg-info-soft text-info-ink',
  danger: 'bg-danger-soft text-danger',
};

const BANNER_ICON: Record<BannerTone, IconName> = {
  warn: 'alert',
  ok: 'check-circle',
  info: 'info',
  danger: 'alert',
};

/** Баннер .bnr: ссылки внутри подчёркнуты и наследуют цвет. */
export function Banner({
  children,
  tone = 'info',
  icon,
  role,
}: {
  children: ReactNode;
  tone?: BannerTone;
  icon?: IconName;
  /** alert — для ошибок, которые нужно зачитать сразу. */
  role?: 'alert' | 'status';
}) {
  return (
    <div
      role={role}
      className={cx(
        'flex items-start gap-2.5 rounded-card px-3.5 py-3 text-sm [&_a]:font-semibold [&_a]:text-inherit [&_a]:underline',
        BANNER[tone],
      )}
    >
      <Icon name={icon ?? BANNER_ICON[tone]} className="mt-px" />
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}

export type EmptyTone = 'accent' | 'neutral' | 'danger';

const EMPTY_TONE: Record<EmptyTone, string> = {
  accent: 'bg-accent-soft text-accent-soft-ink',
  // S49a «нет сети»: подложка поверхности и вторичный цвет — «отключено»
  neutral: 'bg-surface text-text2',
  danger: 'bg-danger-soft text-danger',
};

/** Пустое состояние .empty + .empty-ic. `as` — уровень заголовка по месту на экране
 *  (после h1 экрана — h2): вид тот же, а порядок заголовков для скринридера не ломается.
 *  `size` — вид заголовка: .h3 (по умолчанию) или .h2, как у системных состояний S49. */
export function EmptyState({
  icon,
  title,
  children,
  action,
  as: Tag = 'h3',
  tone = 'accent',
  size = 'h3',
  className,
}: {
  icon: IconName;
  title: ReactNode;
  children?: ReactNode;
  action?: ReactNode;
  as?: 'h1' | 'h2' | 'h3';
  tone?: EmptyTone;
  size?: 'h2' | 'h3';
  /** Отступы по месту: по умолчанию 32/24, как .empty. */
  className?: string;
}) {
  return (
    <div className={cx('flex flex-col items-center gap-3 text-center', className ?? 'px-6 py-8')}>
      <span
        className={cx('flex size-20 items-center justify-center rounded-full', EMPTY_TONE[tone])}
      >
        <Icon name={icon} size={32} />
      </span>
      <Tag className={cx('m-0', size === 'h2' ? 'text-h2' : 'text-h3')}>{title}</Tag>
      {children && <p className="m-0 text-body text-text2">{children}</p>}
      {action}
    </div>
  );
}

/** Тост .toast над таббаром; объявляется скринридеру вежливо. Появляется с подъёмом на 8 px. */
export function Toast({
  children,
  icon = 'check-circle',
  action,
  position = 'fixed',
}: {
  children: ReactNode;
  icon?: IconName;
  action?: ReactNode;
  position?: 'fixed' | 'static';
}) {
  return (
    <div
      role="status"
      aria-live="polite"
      className={cx(
        'flex items-center gap-2.5 rounded-card bg-toast px-3.5 py-3 text-sm text-toast-ink shadow-toast motion-safe:animate-toast-in',
        position === 'fixed' && 'fixed inset-x-4 bottom-25 z-20',
      )}
    >
      <Icon name={icon} />
      <span className="min-w-0 flex-1">{children}</span>
      {action}
    </div>
  );
}

const SKELETON_RADIUS = {
  badge: 'rounded-badge',
  icon: 'rounded-btn-sm',
  field: 'rounded-field',
  card: 'rounded-card',
  round: 'rounded-full',
} as const;

/** Скелетон .skel: размер задаёт раскладка (h-*, w-*), скругление — `radius` по шкале SPEC §2 (по
 *  умолчанию 8, как .skel; иконка строки и маленькая кнопка — icon 10; поле, кнопка и фото — field 12,
 *  как у настоящего фото: угол не прыгает при загрузке; плитки, карточки и варианты — card 16; аватар —
 *  round). Цвет .skel — bg2, как фон экрана: на карточке фигура видна, прямо на фоне экрана — нет.
 *  Там — `screen`: цвет поверхности. Составные скелетоны по форме компонентов — Skeletons.tsx. */
export function Skeleton({
  className,
  round = false,
  radius = round ? 'round' : 'badge',
  screen = false,
}: {
  className?: string;
  round?: boolean;
  radius?: keyof typeof SKELETON_RADIUS;
  screen?: boolean;
}) {
  return (
    <span
      aria-hidden="true"
      className={cx(
        'block motion-safe:animate-pulse',
        screen ? 'bg-surface' : 'bg-bg2',
        SKELETON_RADIUS[radius],
        className,
      )}
    />
  );
}
