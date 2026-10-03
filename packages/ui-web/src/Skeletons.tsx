// Скелетоны по форме настоящих компонентов. На артборде S01 фигуры .skel (bg2) лежат на фоне bg, а
// фон экранов приложения — тоже bg2: голая фигура на нём не видна. Поэтому фигуры — внутри
// поверхности, как у настоящей карточки (.card, .group, .tile), а то, что на макете стоит прямо на
// фоне экрана (подписи полей, заголовки разделов), — фигуры `screen` цвета поверхности. Высота
// строк — как у текста, который придёт: после загрузки раскладка не прыгает. Пульсация — только
// без prefers-reduced-motion; фигуры скрыты от скринридера, статус загрузки объявляет экран.
// Здесь — основа и то, что нужно Главной (первый экран); карточки выдачи, поля и чат —
// CardSkeletons.tsx: Главная их не качает.
import type { ReactNode } from 'react';

import { cx } from './cx.ts';
import { Skeleton } from './Feedback.tsx';
import { Group } from './Group.tsx';

/** Высота строки текста и фигуры в ней — по типошкале ui.css. */
const TEXT = {
  h1: ['h-7.5', 'h-5'],
  h2: ['h-6.5', 'h-4.5'],
  h3: ['h-5.5', 'h-4'],
  title: ['h-5.5', 'h-4'],
  body: ['h-5.5', 'h-3.5'],
  sm: ['h-5', 'h-3'],
  cap: ['h-4.5', 'h-3'],
} as const;

export type SkeletonTextSize = keyof typeof TEXT;

/** Строка текста: занимает высоту строки `size`, ширину задаёт `className` (w-1/2, w-24…). */
export function SkeletonText({
  size = 'body',
  screen = false,
  className,
}: {
  size?: SkeletonTextSize;
  /** Прямо на фоне экрана, а не на карточке. */
  screen?: boolean;
  className?: string;
}) {
  const [line, bar] = TEXT[size];
  return (
    <span aria-hidden="true" className={cx('flex items-center', line, className)}>
      <Skeleton screen={screen} className={cx('w-full', bar)} />
    </span>
  );
}

/** Карточка .card (.tight) на поверхности: фигуры внутри видны в обеих темах. */
export function SkeletonCard({
  children,
  tight = false,
  className,
}: {
  children: ReactNode;
  tight?: boolean;
  className?: string;
}) {
  return (
    <div
      aria-hidden="true"
      className={cx(
        'flex flex-col rounded-card bg-surface p-4',
        tight ? 'gap-2' : 'gap-3',
        className,
      )}
    >
      {children}
    </div>
  );
}

/** Строки .group: слева аватар (диалоги S29), иконка .row-ic (категории S04, уведомления S42) или
 *  ничего, справа — короткое значение (время, число, цена). */
export function RowsSkeleton({
  rows = 3,
  leading = 'avatar',
  subtitle = true,
  trailing = false,
}: {
  rows?: number;
  leading?: 'avatar' | 'icon' | 'none';
  subtitle?: boolean;
  trailing?: boolean;
}) {
  return (
    <Group>
      <div aria-hidden="true">
        {Array.from({ length: rows }, (_, row) => (
          <div
            key={row}
            className="flex min-h-13 items-center gap-3 border-b border-line px-4 py-3 last:border-b-0"
          >
            {leading === 'avatar' && <Skeleton round className="size-10 shrink-0" />}
            {leading === 'icon' && <Skeleton radius="icon" className="size-9 shrink-0" />}
            <div className="flex min-w-0 flex-1 flex-col">
              <SkeletonText className={row % 2 ? 'w-2/5' : 'w-1/2'} />
              {subtitle && <SkeletonText size="cap" className={row % 2 ? 'w-3/4' : 'w-2/3'} />}
            </div>
            {trailing && <SkeletonText size="cap" className="w-12 shrink-0" />}
          </div>
        ))}
      </div>
    </Group>
  );
}

/** Плитка раздела (Tile): иконка 40×40 и подпись. */
export function TileSkeleton() {
  return (
    <div
      aria-hidden="true"
      className="flex min-h-24 flex-col justify-between gap-2 rounded-card bg-surface p-3"
    >
      <Skeleton radius="icon" className="size-10" />
      <SkeletonText size="cap" className="w-3/4" />
    </div>
  );
}

/** Чип (Chip): город, фильтры, группы — пока их подписи не пришли. Ширину задаёт `className`. */
export function ChipSkeleton({ className }: { className?: string }) {
  return (
    <span
      aria-hidden="true"
      className={cx(
        'inline-flex h-10 shrink-0 items-center rounded-chip border border-line bg-surface px-3.5',
        className,
      )}
    >
      <Skeleton className="h-3 w-full" />
    </span>
  );
}
