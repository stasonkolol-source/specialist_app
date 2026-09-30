// Ролик портфолио (шаг 2.2b, ARCHITECTURE §10.4): MP4 H.264 720p с постером. В WebView
// Telegram — playsinline (не разворачивается на весь экран сам); сам не запускается, до
// нажатия грузит только метаданные — трафик не тратится, пока человек не решил смотреть.
// Запускает его человек, поэтому звук обычный: выключить можно в контролах.
import { cx } from './cx.ts';

export interface VideoPlayerProps {
  /** `video.url` из ответа API (MP4). */
  src: string;
  /** Постер — вариант-картинка ролика (`md` или `lg`). */
  poster?: string;
  /** Размеры ролика (`video.width`, `video.height`): место под плеер — до его метаданных. */
  width?: number;
  height?: number;
  /** Подпись для скринридера: что на ролике. */
  label: string;
  /** Размер задаёт раскладка: w-full, max-h-*. */
  className?: string;
}

export function VideoPlayer({ src, poster, width, height, label, className }: VideoPlayerProps) {
  return (
    <video
      src={src}
      poster={poster}
      aria-label={label}
      controls
      playsInline
      preload="metadata"
      style={width && height ? { aspectRatio: `${width} / ${height}` } : undefined}
      className={cx('block w-full rounded-photo bg-bg2 object-contain', className)}
    />
  );
}
