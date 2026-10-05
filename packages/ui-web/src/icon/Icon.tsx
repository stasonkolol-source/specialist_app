// Иконки SPEC §3: скругления, viewBox 24, штрих по размеру. Декоративные (aria-hidden), если нет label.
import { createElement } from 'react';

import { cx } from '../cx.ts';
import type { IconName } from './icons.generated.ts';
import { ICONS } from './icons.generated.ts';

export type { IconName } from './icons.generated.ts';
export const ICON_NAMES = Object.keys(ICONS) as IconName[];

export type IconSize = 16 | 20 | 24 | 28 | 32 | 36;

const SIZE: Record<IconSize, string> = {
  16: 'size-4',
  20: 'size-5',
  24: 'size-6',
  28: 'size-7',
  32: 'size-8',
  36: 'size-9',
};

/** Штрих в единицах viewBox по размеру на экране: с одним 1.8 линия 16 px выходила 1,2 px, 32 px —
 *  2,4 px. Так у всех ≈ 1,5 px (tokens.json icon.strokes, SPEC §3). */
export const ICON_STROKE: Record<IconSize, number> = {
  16: 2.2,
  20: 1.8,
  24: 1.6,
  28: 1.5,
  32: 1.4,
  36: 1.4,
};

export interface IconProps {
  name: IconName;
  size?: IconSize;
  /** Подпись для скринридера — только если иконка несёт смысл без текста рядом. */
  label?: string;
  /** Контур с заливкой тем же цветом: включённое состояние («в избранном» — сердце залито), чтобы
   *  оно читалось не только цветом. */
  filled?: boolean;
  className?: string;
}

export function Icon({ name, size = 20, label, filled = false, className }: IconProps) {
  const icon = ICONS[name];
  const fill = icon.fill;
  return (
    <svg
      viewBox="0 0 24 24"
      className={cx(
        SIZE[size],
        'shrink-0',
        fill
          ? 'fill-current stroke-none'
          : cx(filled ? 'fill-current' : 'fill-none', 'stroke-current'),
        className,
      )}
      strokeWidth={fill ? undefined : ICON_STROKE[size]}
      strokeLinecap="round"
      strokeLinejoin="round"
      {...(label ? { role: 'img', 'aria-label': label } : { 'aria-hidden': true })}
      focusable="false"
    >
      {icon.shapes.map(([tag, attrs], i) => createElement(tag, { key: i, ...attrs }))}
    </svg>
  );
}
