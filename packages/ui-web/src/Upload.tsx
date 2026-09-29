// .add и .ph с прогрессом (S20a, S37): плитка выбора файлов и плитка загрузки.
// Логика загрузки — useMediaUploads (packages/hooks); здесь только вид.
import type { ChangeEvent } from 'react';
import { useRef } from 'react';

import { FOCUS, cx } from './cx.ts';
import type { IconName } from './icon/Icon.tsx';
import { Icon } from './icon/Icon.tsx';

export interface AddTileProps {
  label: string;
  /** `plus` — «Фото или видео» (S37), `camera` — «Добавить» (S20a). */
  icon?: IconName;
  /** Типы для системного выбора файла: `image/*`, `image/*,video/mp4,video/quicktime`. */
  accept: string;
  multiple?: boolean;
  disabled?: boolean;
  onFiles: (files: File[]) => void;
  /** Размер задаёт раскладка: size-18, h-28 w-full. */
  className?: string;
}

/** .add: пунктирная плитка; открывает системный выбор файла (галерея, камера). */
export function AddTile({
  label,
  icon = 'plus',
  accept,
  multiple = false,
  disabled = false,
  onFiles,
  className,
}: AddTileProps) {
  const input = useRef<HTMLInputElement>(null);
  const change = (event: ChangeEvent<HTMLInputElement>) => {
    const files = [...(event.target.files ?? [])];
    // тот же файл, выбранный снова, иначе не даст change
    event.target.value = '';
    if (files.length > 0) onFiles(files);
  };
  return (
    <>
      <button
        type="button"
        disabled={disabled}
        onClick={() => input.current?.click()}
        className={cx(
          'flex shrink-0 flex-col items-center justify-center gap-1 rounded-photo border-[1.5px]',
          'border-dashed border-field bg-transparent text-xs font-medium text-text2',
          'disabled:opacity-50',
          FOCUS,
          className,
        )}
      >
        <Icon name={icon} size={24} />
        {label}
      </button>
      <input
        ref={input}
        type="file"
        accept={accept}
        multiple={multiple}
        hidden
        tabIndex={-1}
        onChange={change}
      />
    </>
  );
}

interface TileBase {
  /** Подпись: «Загрузка 64%» или «Не загрузилось»; в `compact` — только для скринридера. */
  label: string;
  /** Плитка 72 px (S20a): подпись не помещается — видны процент и иконки. */
  compact?: boolean;
  /** Размер задаёт раскладка: size-18, h-28. */
  className?: string;
}

export interface UploadingTileProps extends TileBase {
  state: 'uploading';
  /** Доля отправленного, 0…1. */
  progress: number;
}

export interface FailedTileProps extends TileBase {
  state: 'failed';
  /** Нет — повтор не поможет (файл отклонён): остаётся только «Убрать». */
  onRetry?: () => void;
  retryLabel: string;
  onRemove: () => void;
  removeLabel: string;
}

export type UploadTileProps = UploadingTileProps | FailedTileProps;

const TILE =
  'ph-stripes relative flex shrink-0 flex-col rounded-photo bg-bg2 p-2 text-xs text-text2';
const ROUND = 'inline-flex items-center justify-center rounded-full border-0';

/** .ph загрузки: подпись и полоса 6 px (S37); после сбоя — «Повторить» и «Убрать». */
export function UploadTile(props: UploadTileProps) {
  const { label, compact = false, className } = props;
  if (props.state === 'uploading') {
    const pct = Math.round(Math.max(0, Math.min(1, props.progress)) * 100);
    return (
      <div role="status" className={cx(TILE, 'justify-end gap-1.5', className)}>
        {compact ? (
          <>
            <span className="sr-only">{label}</span>
            <span aria-hidden="true">{pct}%</span>
          </>
        ) : (
          <span>{label}</span>
        )}
        <span aria-hidden="true" className="block h-1.5 overflow-hidden rounded-[4px] bg-line">
          {/* ширина — раскладка, не цвет: inline-стиль допустим */}
          <i className="block h-full rounded-[4px] bg-accent" style={{ width: `${pct}%` }} />
        </span>
      </div>
    );
  }
  const { onRetry, retryLabel, onRemove, removeLabel } = props;
  return (
    <div
      role="alert"
      className={cx(
        TILE,
        // в 72 px по центру иконку задел бы крестик: она уходит в нижний угол
        compact ? 'items-start justify-end' : 'items-center justify-center gap-1 text-center',
        className,
      )}
    >
      <button
        type="button"
        aria-label={removeLabel}
        onClick={onRemove}
        className={cx(ROUND, 'absolute top-1 right-1 size-7 bg-surface text-text', FOCUS)}
      >
        <Icon name="x" size={16} />
      </button>
      {onRetry ? (
        <button
          type="button"
          aria-label={retryLabel}
          onClick={onRetry}
          className={cx(ROUND, 'size-9 bg-danger-soft text-danger', FOCUS)}
        >
          <Icon name="refresh" size={20} />
        </button>
      ) : (
        <span className={cx(ROUND, 'size-9 bg-danger-soft text-danger')}>
          <Icon name="alert" size={20} />
        </span>
      )}
      <span className={compact ? 'sr-only' : 'text-danger'}>{label}</span>
    </div>
  );
}
