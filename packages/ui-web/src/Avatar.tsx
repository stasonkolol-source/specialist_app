// .ava + .av1…av5: инициалы на пастельном фоне или фото; размеры xs 28 / sm 36 / md 48 / lg 88 / xl 104.
// Фото — ссылкой (`src`, пока грузится — размытый ThumbHash `placeholder`, не загрузилось — инициалы)
// или только что выбранным файлом (`file`, превью загрузки S34).
import { useState } from 'react';

import { FileImage } from './FileImage.tsx';
import { cx } from './cx.ts';
import { usePlaceholder } from './thumbhash.ts';

export type AvatarSize = 'xs' | 'sm' | 'md' | 'lg' | 'xl';
export type AvatarPalette = 1 | 2 | 3 | 4 | 5;

const SIZE: Record<AvatarSize, string> = {
  xs: 'size-7 text-avatar-xs',
  sm: 'size-9 text-avatar-sm',
  md: 'size-12 text-avatar-md',
  lg: 'size-22 text-avatar-lg',
  xl: 'size-26 text-avatar-xl',
};

const PALETTE: Record<AvatarPalette, string> = {
  1: 'bg-av1 text-av1-ink',
  2: 'bg-av2 text-av2-ink',
  3: 'bg-av3 text-av3-ink',
  4: 'bg-av4 text-av4-ink',
  5: 'bg-av5 text-av5-ink',
};

/** «Алексей Морозов» → «АМ». */
export function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  return parts
    .slice(0, 2)
    .map((p) => [...p][0]?.toUpperCase() ?? '')
    .join('');
}

/** Стабильный цвет по имени или id: один человек — один цвет на всех экранах. */
export function paletteFor(seed: string): AvatarPalette {
  let hash = 0;
  for (const ch of seed) hash = (hash * 31 + (ch.codePointAt(0) ?? 0)) >>> 0;
  return ((hash % 5) + 1) as AvatarPalette;
}

export interface AvatarProps {
  /** Имя — для инициалов и подписи. */
  name: string;
  size?: AvatarSize;
  palette?: AvatarPalette;
  src?: string;
  /** ThumbHash (base64) фото `src`: размытое превью, пока оно грузится (карточка S05). */
  placeholder?: string | null;
  /** Локальный файл (превью загрузки) — вместо `src`: ссылка на него живёт, пока фото на экране. */
  file?: Blob | null;
  /** Внутри стопки .avs: обводка цветом поверхности. */
  stacked?: boolean;
  className?: string;
}

export function Avatar({
  name,
  size = 'md',
  palette,
  src,
  placeholder,
  file,
  stacked = false,
  className,
}: AvatarProps) {
  const [failed, setFailed] = useState<string | null>(null);
  const blur = usePlaceholder(placeholder);
  const classes = cx(
    'flex shrink-0 items-center justify-center overflow-hidden rounded-full',
    SIZE[size],
    PALETTE[palette ?? paletteFor(name)],
    stacked && 'border-2 border-surface',
    className,
  );
  if (file) {
    return (
      <span className={classes}>
        <FileImage file={file} alt={name} />
      </span>
    );
  }
  if (src && failed !== src) {
    return (
      <img
        src={src}
        alt={name}
        loading="lazy"
        decoding="async"
        style={blur}
        onError={() => setFailed(src)}
        className={cx(classes, 'object-cover')}
      />
    );
  }
  return (
    <span role="img" aria-label={name} className={classes}>
      <span aria-hidden="true">{initials(name)}</span>
    </span>
  );
}
