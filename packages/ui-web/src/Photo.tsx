// .ph / .ph.play: фото работы или плейсхолдер со штриховкой и подписью.
import { useCallback } from 'react';

import { cx } from './cx.ts';
import { Icon } from './icon/Icon.tsx';

export interface PhotoProps {
  /** Нет src и file — плейсхолдер со штриховкой. */
  src?: string;
  /** Локальный файл (превью загрузки): ссылка на него живёт, пока фото на экране. */
  file?: Blob | null;
  /** Описание для скринридера (и подпись плейсхолдера). */
  alt: string;
  /** Видео: иконка «play» по центру. */
  video?: boolean;
  /** Размер задаёт раскладка: size-*, aspect-*, w-full. */
  className?: string;
}

export function Photo({ src, file, alt, video = false, className }: PhotoProps) {
  const frame = cx('relative shrink-0 overflow-hidden rounded-photo bg-bg2', className);
  if (src || file) {
    return (
      <span className={frame}>
        {file ? (
          <FileImage file={file} alt={alt} />
        ) : (
          <img src={src} alt={alt} className="size-full object-cover" />
        )}
        {video && (
          <span className="absolute inset-0 flex items-center justify-center text-knob">
            <Icon name="play" size={32} />
          </span>
        )}
      </span>
    );
  }
  return (
    <span
      role="img"
      aria-label={alt}
      className={cx(
        frame,
        'ph-stripes flex p-2 text-xs text-text2',
        video ? 'items-center justify-center' : 'items-end justify-start',
      )}
    >
      {video ? <Icon name="play" size={32} /> : <span aria-hidden="true">{alt}</span>}
    </span>
  );
}

/** blob: URL создаётся при монтировании и отзывается при снятии: без утечки памяти на превью. */
function FileImage({ file, alt }: { file: Blob; alt: string }) {
  const attach = useCallback(
    (node: HTMLImageElement | null) => {
      if (!node) return;
      const url = URL.createObjectURL(file);
      node.src = url;
      return () => URL.revokeObjectURL(url);
    },
    [file],
  );
  return <img ref={attach} alt={alt} className="size-full object-cover" />;
}
