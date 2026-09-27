// .fld > .lbl + .inp / textarea.inp, .hint, .err, .inp.focus, .inp.error, .inp .sfx; .search.
import type { InputHTMLAttributes, ReactNode, TextareaHTMLAttributes } from 'react';
import { cloneElement, isValidElement, useId } from 'react';

import { cx } from '../cx.ts';
import { Icon } from '../icon/Icon.tsx';

const FRAME =
  'w-full rounded-field border bg-surface text-input text-text focus-within:border-accent focus-within:ring-3 focus-within:ring-accent-soft';
const BARE =
  'min-w-0 flex-1 border-0 bg-transparent p-0 text-input text-text outline-none placeholder:text-text2';

export interface FieldProps {
  label: ReactNode;
  hint?: ReactNode;
  /** Текст ошибки: поле подсвечивается, скринридер его зачитывает. */
  error?: ReactNode;
  /** Один Input или Textarea: id и aria-* проставляются сами. */
  children: ReactNode;
}

export function Field({ label, hint, error, children }: FieldProps) {
  const id = useId();
  const hintId = hint ? `${id}-hint` : undefined;
  const errorId = error ? `${id}-error` : undefined;
  const describedBy = [errorId, hintId].filter(Boolean).join(' ') || undefined;
  const control = isValidElement<{ id?: string; invalid?: boolean; 'aria-describedby'?: string }>(
    children,
  )
    ? cloneElement(children, { id, invalid: Boolean(error), 'aria-describedby': describedBy })
    : children;
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-sm font-semibold">
        {label}
      </label>
      {control}
      {error && (
        <p id={errorId} className="m-0 text-cap text-danger">
          {error}
        </p>
      )}
      {hint && (
        <p id={hintId} className="m-0 text-cap">
          {hint}
        </p>
      )}
    </div>
  );
}

export interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  /** Суффикс в поле («RSD»). */
  suffix?: ReactNode;
  invalid?: boolean;
}

export function Input({ suffix, invalid = false, className, ...rest }: InputProps) {
  return (
    <div
      className={cx(
        FRAME,
        'flex h-12 items-center gap-2 px-3.5',
        invalid ? 'border-danger' : 'border-field',
        className,
      )}
    >
      <input {...rest} aria-invalid={invalid || undefined} className={cx(BARE, 'h-full')} />
      {suffix && <span className="ml-auto font-semibold text-text2">{suffix}</span>}
    </div>
  );
}

export interface TextareaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  invalid?: boolean;
}

export function Textarea({ invalid = false, className, ...rest }: TextareaProps) {
  return (
    <textarea
      {...rest}
      aria-invalid={invalid || undefined}
      className={cx(
        FRAME,
        'block min-h-26 resize-none px-3.5 py-3 outline-none placeholder:text-text2',
        invalid ? 'border-danger' : 'border-field',
        className,
      )}
    />
  );
}

export interface SearchFieldProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'type'> {
  /** Подпись поля для скринридера (видимой метки у поиска нет). */
  label: string;
  /** Кнопка фильтров и т. п. справа. */
  trailing?: ReactNode;
}

export function SearchField({ label, trailing, className, ...rest }: SearchFieldProps) {
  return (
    <div
      role="search"
      className={cx(
        'flex h-12 items-center gap-2.5 rounded-panel border border-line bg-surface px-3.5 text-text2 focus-within:border-accent',
        className,
      )}
    >
      <Icon name="search" />
      <input {...rest} type="search" aria-label={label} className={cx(BARE, 'h-full')} />
      {trailing}
    </div>
  );
}
