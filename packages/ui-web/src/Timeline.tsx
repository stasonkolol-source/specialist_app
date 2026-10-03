import type { ReactNode } from 'react';

import { cx } from './cx.ts';
import { Icon } from './icon/Icon.tsx';

export type TimelineState = 'done' | 'now' | 'next';

export interface TimelineItem {
  key: string;
  title: ReactNode;
  /** Справа: время вехи или пояснение («работа в 19:00»). */
  meta?: ReactNode;
  state: TimelineState;
}

/** Таймлайн .tl (S26): пройденные вехи с галочкой и линией цвета акцента, текущая — с кольцом
 *  (`aria-current="step"`), будущие — серым. */
export function Timeline({ items, label }: { items: readonly TimelineItem[]; label?: string }) {
  return (
    <ol aria-label={label} className="m-0 flex list-none flex-col p-0">
      {items.map((item, index) => {
        const last = index === items.length - 1;
        return (
          <li
            key={item.key}
            aria-current={item.state === 'now' ? 'step' : undefined}
            className={cx('relative flex gap-3', !last && 'pb-4')}
          >
            {!last && (
              <span
                aria-hidden="true"
                className={cx(
                  'absolute top-[26px] bottom-0.5 left-[11px] w-0.5',
                  item.state === 'done' ? 'bg-accent' : 'bg-line',
                )}
              />
            )}
            <span
              aria-hidden="true"
              className={cx(
                'flex size-6 flex-none items-center justify-center rounded-full border-2 text-accent-ink',
                item.state === 'done' && 'border-accent bg-accent',
                item.state === 'now' &&
                  'border-accent bg-surface shadow-[0_0_0_4px_var(--color-accent-soft)]',
                item.state === 'next' && 'border-field bg-surface',
              )}
            >
              {item.state === 'done' && <Icon name="check" size={16} className="stroke-[2.6]" />}
            </span>
            <span className="flex min-w-0 grow items-start justify-between gap-3 pt-0.5">
              <span
                className={cx(
                  item.state === 'now' && 'font-semibold',
                  item.state === 'next' && 'text-text2',
                )}
              >
                {item.title}
              </span>
              {item.meta && <span className="shrink-0 text-cap text-text2">{item.meta}</span>}
            </span>
          </li>
        );
      })}
    </ol>
  );
}
