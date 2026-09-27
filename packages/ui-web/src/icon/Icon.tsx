// Иконки SPEC §3: штрих 1.8, скругления, viewBox 24. Декоративные (aria-hidden), если нет label.
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

export interface IconProps {
  name: IconName;
  size?: IconSize;
  /** Подпись для скринридера — только если иконка несёт смысл без текста рядом. */
  label?: string;
  className?: string;
}

export function Icon({ name, size = 20, label, className }: IconProps) {
  const icon = ICONS[name];
  const fill = icon.fill;
  return (
    <svg
      viewBox="0 0 24 24"
      className={cx(
        SIZE[size],
        'shrink-0',
        fill ? 'fill-current stroke-none' : 'fill-none stroke-current',
        className,
      )}
      strokeWidth={fill ? undefined : 1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      {...(label ? { role: 'img', 'aria-label': label } : { 'aria-hidden': true })}
      focusable="false"
    >
      {icon.shapes.map(([tag, attrs], i) => createElement(tag, { key: i, ...attrs }))}
    </svg>
  );
}
