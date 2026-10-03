// .ph / .ph.play: фото работы или плейсхолдер со штриховкой и подписью.
// Фото с сервера (шаг 2.2a): сразу — размытый ThumbHash, затем WebP-вариант нужного размера
// (srcset: браузер берёт по ширине на экране и плотности пикселей), с плавным появлением; так же —
// одна ссылка `src` (фото заявок S12–S15). Грузится, когда доезжает до экрана, и декодируется не в
// главном потоке; главное фото экрана (`priority`) — сразу и первым. Не загрузилось — снова
// плейсхолдер с подписью. В просмотрщике S10 фото целиком, во всю ширину экрана: без обрезки и
// скругления (`fit="contain"`). Локальный файл (превью загрузки) — как есть, без плейсхолдера.
import { useState } from 'react';

import { FileImage } from './FileImage.tsx';
import { cx } from './cx.ts';
import { Icon } from './icon/Icon.tsx';
import { usePlaceholder } from './thumbhash.ts';

export interface PhotoVariant {
  url: string;
  width: number;
}

export type PhotoFit = 'cover' | 'contain';

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
  /** Описание для скринридера (и подпись плейсхолдера); пустое — фото декоративное: подпись
   *  у того, что вокруг (миниатюра-кнопка S10). */
  alt: string;
  /** Видео: иконка «play» по центру. */
  video?: boolean;
  /** cover — плитка (обрезка по рамке); contain — фото целиком, без скругления (просмотрщик S10). */
  fit?: PhotoFit;
  /** Главное фото экрана (первое на S15, открытое в S10): грузится сразу и раньше остальных. */
  priority?: boolean;
  /** Размер задаёт раскладка: size-*, aspect-*, w-full. */
  className?: string;
}

/** `auto` — ширина по раскладке (с loading="lazy"); где его не знают — вся ширина. */
const AUTO_SIZES = 'auto, 100vw';

const frame = (className: string | undefined, fit: PhotoFit = 'cover') =>
  cx('relative shrink-0 overflow-hidden bg-bg2', fit === 'cover' && 'rounded-photo', className);

const FIT: Record<PhotoFit, string> = { cover: 'object-cover', contain: 'object-contain' };

export function Photo({
  src,
  variants = [],
  placeholder,
  sizes = AUTO_SIZES,
  file,
  alt,
  video = false,
  fit = 'cover',
  priority = false,
  className,
}: PhotoProps) {
  if (!file && (variants.length > 0 || src)) {
    const sized = variants.length > 0;
    // старым WebView без srcset — средний вариант
    const fallback = sized ? variants[Math.floor((variants.length - 1) / 2)]?.url : src;
    const srcSet = sized
      ? variants.map((variant) => `${variant.url} ${variant.width}w`).join(', ')
      : undefined;
    // другие варианты — новое фото: загрузка заново. Подпись presigned-ссылки меняется при
    // каждом запросе — ключ без неё, иначе фото мигало бы на каждом обновлении
    const identity = (sized ? variants.map((variant) => variant.url) : [src ?? ''])
      .map((url) => url.split('?')[0])
      .join(' ');
    return (
      <ServerPhoto
        key={identity}
        src={fallback}
        srcSet={srcSet}
        sizes={srcSet ? sizes : undefined}
        placeholder={placeholder}
        alt={alt}
        video={video}
        fit={fit}
        priority={priority}
        className={className}
      />
    );
  }
  if (file) {
    return (
      <span className={frame(className, fit)}>
        <FileImage file={file} alt={alt} />
        {video && <Play />}
      </span>
    );
  }
  return <Stripes alt={alt} video={video} fit={fit} className={className} />;
}

function Stripes({
  alt,
  video,
  fit,
  className,
}: {
  alt: string;
  video: boolean;
  fit: PhotoFit;
  className?: string;
}) {
  return (
    <span
      role={alt ? 'img' : undefined}
      aria-label={alt || undefined}
      aria-hidden={alt ? undefined : true}
      className={cx(
        frame(className, fit),
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

/** Фото с сервера появляется плавно поверх размытого превью; не загрузилось — штриховка. */
function ServerPhoto({
  src,
  srcSet,
  sizes,
  placeholder,
  alt,
  video,
  fit,
  priority,
  className,
}: {
  src: string | undefined;
  srcSet: string | undefined;
  sizes: string | undefined;
  placeholder: string | null | undefined;
  alt: string;
  video: boolean;
  fit: PhotoFit;
  priority: boolean;
  className: string | undefined;
}) {
  const [phase, setPhase] = useState<'loading' | 'loaded' | 'failed'>('loading');
  const blur = usePlaceholder(placeholder);
  if (phase === 'failed') {
    return <Stripes alt={alt} video={video} fit={fit} className={className} />;
  }
  return (
    // превью убирается после загрузки: иначе просвечивало бы сквозь прозрачные PNG
    <span className={frame(className, fit)} style={phase === 'loaded' ? undefined : blur}>
      <img
        src={src}
        srcSet={srcSet}
        sizes={sizes}
        alt={alt}
        loading={priority ? 'eager' : 'lazy'}
        fetchPriority={priority ? 'high' : undefined}
        decoding="async"
        onLoad={() => setPhase('loaded')}
        onError={() => setPhase('failed')}
        className={cx(
          'size-full transition-opacity duration-200',
          FIT[fit],
          phase === 'loaded' ? 'opacity-100' : 'opacity-0',
        )}
      />
      {video && <Play />}
    </span>
  );
}
