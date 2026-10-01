// .ph / .ph.play: фото работы или плейсхолдер со штриховкой и подписью.
// Фото с сервера (шаг 2.2a): сразу — размытый ThumbHash, затем WebP-вариант нужного размера
// (srcset: браузер берёт по ширине на экране и плотности пикселей), с плавным появлением.
// Вариант не загрузился — снова плейсхолдер с подписью.
import type { CSSProperties } from 'react';
import { useMemo, useState } from 'react';
import { thumbHashToDataURL } from 'thumbhash';

import { FileImage } from './FileImage.tsx';
import { cx } from './cx.ts';
import { Icon } from './icon/Icon.tsx';

export interface PhotoVariant {
  url: string;
  width: number;
}

export interface PhotoProps {
  /** Нет src, variants и file — плейсхолдер со штриховкой. */
  src?: string;
  /** Варианты с сервера (320, 800, 1600 px): браузер выбирает по `sizes`. */
  variants?: readonly PhotoVariant[];
  /** ThumbHash в base64: размытое превью, пока грузится фото. */
  placeholder?: string | null;
  /** Ширина фото на экране для srcset (`33vw`, `114px`); по умолчанию браузер меряет сам. */
  sizes?: string;
  /** Локальный файл (превью загрузки): ссылка на него живёт, пока фото на экране. */
  file?: Blob | null;
  /** Описание для скринридера (и подпись плейсхолдера). */
  alt: string;
  /** Видео: иконка «play» по центру. */
  video?: boolean;
  /** Размер задаёт раскладка: size-*, aspect-*, w-full. */
  className?: string;
}

/** `auto` — ширина по раскладке (с loading="lazy"); где его не знают — вся ширина. */
const AUTO_SIZES = 'auto, 100vw';

const frame = (className: string | undefined) =>
  cx('relative shrink-0 overflow-hidden rounded-photo bg-bg2', className);

export function Photo({
  src,
  variants = [],
  placeholder,
  sizes = AUTO_SIZES,
  file,
  alt,
  video = false,
  className,
}: PhotoProps) {
  if (!file && variants.length > 0) {
    const srcSet = variants.map((variant) => `${variant.url} ${variant.width}w`).join(', ');
    // другие варианты — новое фото: загрузка заново. Подпись presigned-ссылки меняется при
    // каждом запросе — ключ без неё, иначе фото мигало бы на каждом обновлении
    const identity = variants.map((variant) => variant.url.split('?')[0]).join(' ');
    return (
      <ServerPhoto
        key={identity}
        variants={variants}
        srcSet={srcSet}
        sizes={sizes}
        placeholder={placeholder}
        alt={alt}
        video={video}
        className={className}
      />
    );
  }
  if (src || file) {
    return (
      <span className={frame(className)}>
        {file ? (
          <FileImage file={file} alt={alt} />
        ) : (
          <img src={src} alt={alt} className="size-full object-cover" />
        )}
        {video && <Play />}
      </span>
    );
  }
  return <Stripes alt={alt} video={video} className={className} />;
}

function Stripes({ alt, video, className }: { alt: string; video: boolean; className?: string }) {
  return (
    <span
      role="img"
      aria-label={alt}
      className={cx(
        frame(className),
        'ph-stripes flex p-2 text-xs text-text2',
        video ? 'items-center justify-center' : 'items-end justify-start',
      )}
    >
      {video ? <Icon name="play" size={32} /> : <span aria-hidden="true">{alt}</span>}
    </span>
  );
}

function Play() {
  return (
    <span className="absolute inset-0 flex items-center justify-center text-knob">
      <Icon name="play" size={32} />
    </span>
  );
}

/** ThumbHash → PNG data URL фоном рамки; битый хэш — без превью. */
function usePlaceholder(placeholder: string | null | undefined): CSSProperties | undefined {
  return useMemo(() => {
    if (!placeholder) return undefined;
    try {
      const bytes = Uint8Array.from(atob(placeholder), (char) => char.charCodeAt(0));
      return { backgroundImage: `url(${thumbHashToDataURL(bytes)})`, backgroundSize: 'cover' };
    } catch {
      return undefined;
    }
  }, [placeholder]);
}

/** Вариант с сервера появляется плавно поверх размытого превью; не загрузился — штриховка. */
function ServerPhoto({
  variants,
  srcSet,
  sizes,
  placeholder,
  alt,
  video,
  className,
}: {
  variants: readonly PhotoVariant[];
  srcSet: string;
  sizes: string;
  placeholder: string | null | undefined;
  alt: string;
  video: boolean;
  className: string | undefined;
}) {
  const [phase, setPhase] = useState<'loading' | 'loaded' | 'failed'>('loading');
  const blur = usePlaceholder(placeholder);
  if (phase === 'failed') return <Stripes alt={alt} video={video} className={className} />;
  // старым WebView без srcset — средний вариант
  const fallback = variants[Math.floor((variants.length - 1) / 2)]?.url;
  return (
    // превью убирается после загрузки: иначе просвечивало бы сквозь прозрачные PNG
    <span className={frame(className)} style={phase === 'loaded' ? undefined : blur}>
      <img
        src={fallback}
        srcSet={srcSet}
        sizes={sizes}
        alt={alt}
        loading="lazy"
        decoding="async"
        onLoad={() => setPhase('loaded')}
        onError={() => setPhase('failed')}
        className={cx(
          'size-full object-cover transition-opacity duration-200',
          phase === 'loaded' ? 'opacity-100' : 'opacity-0',
        )}
      />
      {video && <Play />}
    </span>
  );
}
