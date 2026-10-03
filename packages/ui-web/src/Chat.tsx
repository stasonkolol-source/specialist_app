// Чат по классам design/ui.css (S30, D30): лента .msgs, пузыри .bub in/out со временем .tm,
// системные строки .sysmsg, скрытый контакт .mask и композер .composer над клавиатурой.
import type { FormEvent, KeyboardEvent, ReactNode } from 'react';
import { useId, useLayoutEffect, useRef } from 'react';

import { cx } from './cx.ts';
import type { IconName } from './icon/Icon.tsx';
import { Icon } from './icon/Icon.tsx';

/** Знак, которым сервер заменяет телефон, ссылку или @username до договорённости. */
export const MASK = '•••';

/** Лента сообщений (.msgs): новые объявляет экранный диктор. */
export function ChatList({
  children,
  label,
  className,
}: {
  children: ReactNode;
  label: string;
  className?: string;
}) {
  return (
    <div
      role="log"
      aria-live="polite"
      aria-label={label}
      className={cx('flex flex-col gap-2 p-3', className)}
    >
      {children}
    </div>
  );
}

export interface BubbleProps {
  /** `out` — своё сообщение (справа, акцент), `in` — собеседника. */
  side: 'in' | 'out';
  children: ReactNode;
  /** Время под текстом (.tm). */
  time?: string;
  /** Строка под временем: «Отправляется…», «Не отправлено — повторить». */
  status?: ReactNode;
  /** Сообщение не ушло: пузырь бледнее, нажатие повторяет отправку. */
  failed?: boolean;
  onRetry?: () => void;
}

export function Bubble({ side, children, time, status, failed = false, onRetry }: BubbleProps) {
  const classes = cx(
    'max-w-[80%] whitespace-pre-wrap break-words px-3 pt-2 pb-1.5 text-left text-[15px] leading-[21px]',
    side === 'out'
      ? 'self-end rounded-[18px] rounded-br-[6px] bg-accent text-accent-ink'
      : 'self-start rounded-[18px] rounded-bl-[6px] bg-surface text-text',
    failed && 'opacity-60',
  );
  const footer = (
    <>
      {time && (
        <span className="mt-0.5 block text-right text-[11px] leading-[14px] opacity-80">
          {time}
        </span>
      )}
      {status && (
        <span className="mt-0.5 block text-right text-[11px] leading-[14px] opacity-90">
          {status}
        </span>
      )}
    </>
  );
  if (failed && onRetry) {
    return (
      <button type="button" onClick={onRetry} className={cx(classes, 'border-0')}>
        {children}
        {footer}
      </button>
    );
  }
  return (
    <div className={classes}>
      {children}
      {footer}
    </div>
  );
}

/** Системная строка по центру ленты (.sysmsg): контекст диалога, что со сделкой, подсказки. */
export function SystemNote({ children, icon }: { children: ReactNode; icon?: IconName }) {
  return (
    <p className="m-0 flex max-w-[92%] items-center gap-1.5 self-center rounded-xl bg-surface px-3 py-1.5 text-center text-[13px] leading-[18px] text-text2">
      {icon && <Icon name={icon} size={16} />}
      <span>{children}</span>
    </p>
  );
}

/** Текст с контактами, скрытыми сервером: «•••» — плашкой .mask. */
export function MaskedText({ text }: { text: string }) {
  const parts = text.split(MASK);
  return (
    <>
      {parts.map((part, index) => (
        // части текста не переставляются: индекс — устойчивый ключ
        <span key={index}>
          {part}
          {index < parts.length - 1 && (
            <span className="inline-block rounded-md bg-[rgb(91_98_112/0.18)] px-1.5 font-semibold tracking-[0.04em]">
              {MASK}
            </span>
          )}
        </span>
      ))}
    </>
  );
}

export interface ComposerProps {
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  placeholder: string;
  /** Подпись поля для диктора: «Сообщение Алексею». */
  label: string;
  sendLabel: string;
  disabled?: boolean;
  maxLength?: number;
  /** Отступ снизу: безопасная зона телефона (кнопки системы, «чёлка» снизу). */
  bottomInset?: number;
}

const MAX_ROWS_HEIGHT = 120;

/** Композер (.composer): многострочное поле растёт до пяти строк, «Отправить» — круглая кнопка
 *  акцента; Enter с Shift — перенос строки, без — отправка (на телефоне — кнопкой). */
export function Composer({
  value,
  onChange,
  onSend,
  placeholder,
  label,
  sendLabel,
  disabled = false,
  maxLength,
  bottomInset = 0,
}: ComposerProps) {
  const field = useRef<HTMLTextAreaElement>(null);
  const id = useId();
  const ready = !disabled && value.trim().length > 0;

  useLayoutEffect(() => {
    const node = field.current;
    if (!node) return;
    node.style.height = 'auto';
    node.style.height = `${Math.min(node.scrollHeight, MAX_ROWS_HEIGHT)}px`;
  }, [value]);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (ready) onSend();
  };
  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      if (ready) onSend();
    }
  };

  return (
    <form
      onSubmit={submit}
      className="sticky bottom-0 z-10 flex items-end gap-2 border-0 border-t border-solid border-line bg-bg px-2.5 pt-2"
      style={{ paddingBottom: bottomInset + 8 }}
    >
      <label htmlFor={id} className="sr-only">
        {label}
      </label>
      <textarea
        id={id}
        ref={field}
        rows={1}
        value={value}
        maxLength={maxLength}
        disabled={disabled}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={onKeyDown}
        className="min-h-11 flex-1 resize-none rounded-[22px] border border-solid border-line bg-bg2 px-4 py-[11px] text-input text-text outline-none focus:border-accent disabled:opacity-60"
      />
      <button
        type="submit"
        aria-label={sendLabel}
        disabled={!ready}
        className="flex size-11 shrink-0 items-center justify-center rounded-full border-0 bg-accent text-accent-ink disabled:opacity-40"
      >
        <Icon name="send" size={24} />
      </button>
    </form>
  );
}
