// .seg, .opt + .radio/.chk, .sw из ui.css: выбор одного, нескольких и переключатель.
import type { KeyboardEvent, ReactNode } from 'react';
import { useRef } from 'react';

import { FOCUS, cx } from '../cx.ts';
import type { IconName } from '../icon/Icon.tsx';
import { Icon } from '../icon/Icon.tsx';

export interface SegmentedOption<T extends string> {
  value: T;
  label: ReactNode;
  icon?: IconName;
}

/** Сегменты (.seg): radiogroup, стрелки влево-вправо меняют выбор. */
export function Segmented<T extends string>({
  options,
  value,
  onChange,
  label,
}: {
  options: SegmentedOption<T>[];
  value: T;
  onChange: (value: T) => void;
  label: string;
}) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const onKey = (e: KeyboardEvent, i: number) => {
    const step = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0;
    if (!step) return;
    e.preventDefault();
    const next = (i + step + options.length) % options.length;
    const option = options[next];
    if (!option) return;
    onChange(option.value);
    refs.current[next]?.focus();
  };
  return (
    <div
      role="radiogroup"
      aria-label={label}
      className="grid auto-cols-fr grid-flow-col gap-0.75 rounded-btn bg-bg2 p-0.75"
    >
      {options.map((o, i) => {
        const on = o.value === value;
        return (
          <button
            key={o.value}
            ref={(el) => {
              refs.current[i] = el;
            }}
            type="button"
            role="radio"
            aria-checked={on}
            tabIndex={on ? 0 : -1}
            onClick={() => onChange(o.value)}
            onKeyDown={(e) => onKey(e, i)}
            className={cx(
              'flex h-10 items-center justify-center gap-1.5 whitespace-nowrap rounded-seg-item border-0 text-sm font-semibold',
              on ? 'bg-surface text-text shadow-seg' : 'bg-transparent text-text2',
              FOCUS,
            )}
          >
            {o.icon && <Icon name={o.icon} size={16} />}
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

export interface OptionProps {
  title: ReactNode;
  description?: ReactNode;
  checked: boolean;
  onChange: (checked: boolean) => void;
  /** radio — один из группы (.radio), checkbox — несколько (.chk). */
  kind?: 'radio' | 'checkbox';
  icon?: IconName;
}

/** Карточка выбора .opt / .opt.on. */
export function Option({
  title,
  description,
  checked,
  onChange,
  kind = 'radio',
  icon,
}: OptionProps) {
  return (
    <button
      type="button"
      role={kind}
      aria-checked={checked}
      onClick={() => onChange(kind === 'radio' ? true : !checked)}
      className={cx(
        'flex min-h-14 w-full items-center gap-3 rounded-panel border bg-surface px-3.5 py-3 text-left text-text',
        checked ? 'border-accent ring-1 ring-accent ring-inset' : 'border-line',
        FOCUS,
      )}
    >
      {icon && <Icon name={icon} className="text-text2" />}
      <span className="flex min-w-0 flex-1 flex-col">
        <span className="text-body">{title}</span>
        {description && <span className="text-cap text-text2">{description}</span>}
      </span>
      {kind === 'radio' ? (
        <span
          aria-hidden="true"
          className={cx(
            'size-5.5 shrink-0 rounded-full',
            checked ? 'border-7 border-accent' : 'border-2 border-field',
          )}
        />
      ) : (
        <span
          aria-hidden="true"
          className={cx(
            'flex size-5.5 shrink-0 items-center justify-center rounded-check border-2 text-accent-ink',
            checked ? 'border-accent bg-accent' : 'border-field',
          )}
        >
          {checked && <Icon name="check" size={16} />}
        </span>
      )}
    </button>
  );
}

/** Переключатель .sw / .sw.on (role=switch). */
export function Switch({
  checked,
  onChange,
  label,
  disabled = false,
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label: string;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cx(
        'relative h-7.75 w-12.75 shrink-0 rounded-full border-0 p-0 disabled:opacity-50',
        checked ? 'bg-accent' : 'bg-field',
        FOCUS,
      )}
    >
      <span
        aria-hidden="true"
        className={cx(
          'absolute top-0.5 size-6.75 rounded-full bg-knob shadow-knob transition-all',
          checked ? 'left-5.5' : 'left-0.5',
        )}
      />
    </button>
  );
}
