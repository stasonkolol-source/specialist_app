// .seg, .opt + .radio/.chk, .sw из ui.css: выбор одного, нескольких и переключатель.
import type { KeyboardEvent, ReactNode, Ref } from 'react';
import { useId, useRef } from 'react';

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
  /** Слева вместо иконки: плитка RowIcon (намерение S02b). */
  leading?: ReactNode;
  /** Справа перед отметкой: бейдж «скоро» (S02a). */
  trailing?: ReactNode;
  /** Где отметка: справа (по умолчанию) или слева, как в выборе языка и города S02a. */
  control?: 'start' | 'end';
  /** Крупная карточка S02b: заголовок .h3, описание .sm, выравнивание по верху. */
  large?: boolean;
  /** Недоступно («скоро»): приглушено, как на артборде (opacity .55), не нажимается. */
  disabled?: boolean;
}

/** Карточка выбора .opt / .opt.on. */
export function Option({
  title,
  description,
  checked,
  onChange,
  kind = 'radio',
  icon,
  leading,
  trailing,
  control = 'end',
  large = false,
  disabled = false,
}: OptionProps) {
  const id = useId();
  const mark = <Mark kind={kind} checked={checked} className={cx(large && 'mt-2.75')} />;
  // Имя — заголовок, описание и бейдж — подсказка: иначе скринридер слил бы их без пробела
  const described = [description && `${id}-d`, trailing && `${id}-b`].filter(Boolean).join(' ');
  return (
    <button
      type="button"
      role={kind}
      aria-checked={checked}
      aria-labelledby={`${id}-t`}
      aria-describedby={described || undefined}
      disabled={disabled}
      onClick={() => onChange(kind === 'radio' ? true : !checked)}
      className={cx(
        'flex min-h-14 w-full gap-3 rounded-panel border bg-surface px-3.5 py-3 text-left text-text disabled:opacity-55',
        large ? 'items-start' : 'items-center',
        checked ? 'border-accent ring-1 ring-accent ring-inset' : 'border-line',
        FOCUS,
      )}
    >
      {control === 'start' && mark}
      {leading ?? (icon && <Icon name={icon} className="text-text2" />)}
      <span className={cx('flex min-w-0 flex-1 flex-col', large && 'gap-1')}>
        <span id={`${id}-t`} className={large ? 'text-h3' : 'text-body'}>
          {title}
        </span>
        {description && (
          <span id={`${id}-d`} className={large ? 'text-sm text-text2' : 'text-cap text-text2'}>
            {description}
          </span>
        )}
      </span>
      {trailing && <span id={`${id}-b`}>{trailing}</span>}
      {control === 'end' && mark}
    </button>
  );
}

/** Отметка .radio / .chk: состояние читает скринридер у кнопки, сама отметка скрыта. */
function Mark({
  kind,
  checked,
  invalid = false,
  className,
}: {
  kind: 'radio' | 'checkbox';
  checked: boolean;
  invalid?: boolean;
  className?: string;
}) {
  if (kind === 'radio') {
    return (
      <span
        aria-hidden="true"
        className={cx(
          'size-5.5 shrink-0 rounded-full',
          checked ? 'border-7 border-accent' : 'border-2 border-field',
          className,
        )}
      />
    );
  }
  return (
    <span
      aria-hidden="true"
      className={cx(
        'flex size-5.5 shrink-0 items-center justify-center rounded-check border-2 text-accent-ink',
        checked ? 'border-accent bg-accent' : invalid ? 'border-danger' : 'border-field',
        className,
      )}
    >
      {checked && <Icon name="check" size={16} />}
    </span>
  );
}

export interface CheckboxProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  /** Подпись: вся строка нажимается и называет галочку для скринридера. */
  children: ReactNode;
  /** Галочка обязательна, а её нет: рамка отметки — цветом ошибки, aria-invalid. */
  invalid?: boolean;
  /** id текста ошибки или подсказки под галочкой. */
  describedBy?: string;
  /** Оформление строки по месту: карточка S02c — `rounded-card bg-surface p-4`. */
  className?: string;
  ref?: Ref<HTMLButtonElement>;
}

/** Галочка .chk с подписью (S02c «Мне есть 18 лет, я принимаю правила площадки»). */
export function Checkbox({
  checked,
  onChange,
  children,
  invalid = false,
  describedBy,
  className,
  ref,
}: CheckboxProps) {
  return (
    <button
      ref={ref}
      type="button"
      role="checkbox"
      aria-checked={checked}
      aria-invalid={invalid || undefined}
      aria-describedby={describedBy}
      onClick={() => onChange(!checked)}
      className={cx(
        'flex w-full items-start gap-3 border-0 text-left text-body text-text',
        FOCUS,
        className,
      )}
    >
      <Mark kind="checkbox" checked={checked} invalid={invalid} className="mt-px" />
      <span className="min-w-0 flex-1">{children}</span>
    </button>
  );
}

const NEXT_KEYS: Record<string, number> = {
  ArrowDown: 1,
  ArrowRight: 1,
  ArrowUp: -1,
  ArrowLeft: -1,
};

/**
 * Группа Option-радио: стрелки переводят фокус и выбор на соседний доступный вариант
 * (WAI-ARIA radio group), недоступные («скоро») пропускаются.
 */
export function RadioGroup({
  children,
  label,
  labelledBy,
  busy,
  className,
}: {
  children: ReactNode;
  label?: string;
  labelledBy?: string;
  /** Выбор сохраняется на сервере. */
  busy?: boolean;
  className?: string;
}) {
  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const step = NEXT_KEYS[event.key];
    if (!step) return;
    const radios = [
      ...event.currentTarget.querySelectorAll<HTMLButtonElement>('[role="radio"]:not(:disabled)'),
    ];
    const index = radios.findIndex((radio) => radio === document.activeElement);
    if (index < 0) return;
    event.preventDefault();
    const next = radios[(index + step + radios.length) % radios.length];
    next?.focus();
    next?.click();
  };
  return (
    <div
      role="radiogroup"
      aria-label={label}
      aria-labelledby={labelledBy}
      aria-busy={busy}
      onKeyDown={onKeyDown}
      className={className}
    >
      {children}
    </div>
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
