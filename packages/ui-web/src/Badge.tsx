// .bdg ok/urg/info/mute/pro/dng: бейдж называет факт («Телефон подтверждён», «Срочно»).
import type { ReactNode } from 'react';

import { cx } from './cx.ts';
import type { IconName } from './icon/Icon.tsx';
import { Icon } from './icon/Icon.tsx';

export type BadgeTone = 'ok' | 'urgent' | 'info' | 'mute' | 'pro' | 'danger';

const TONE: Record<BadgeTone, string> = {
  ok: 'bg-accent-soft text-accent-soft-ink',
  urgent: 'bg-urgent-soft text-urgent-soft-ink',
  info: 'bg-info-soft text-info-ink',
  mute: 'bg-bg2 text-text2',
  pro: 'bg-text text-bg',
  danger: 'bg-danger-soft text-danger',
};

export function Badge({
  children,
  tone = 'mute',
  icon,
  dot = false,
  className,
}: {
  children: ReactNode;
  tone?: BadgeTone;
  icon?: IconName;
  /** .dot — точка-индикатор («Сегодня до 20:00» в карточке S05). */
  dot?: boolean;
  className?: string;
}) {
  return (
    <span
      className={cx(
        'inline-flex h-6 shrink-0 items-center gap-1 whitespace-nowrap rounded-badge px-2 text-badge',
        TONE[tone],
        className,
      )}
    >
      {dot && <span className="size-2 shrink-0 rounded-full bg-accent" aria-hidden="true" />}
      {icon && <Icon name={icon} size={16} />}
      {children}
    </span>
  );
}
