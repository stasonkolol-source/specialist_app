// .map, .zone, .pin (ui.css): схема улиц вместо карты — заглушка с артбордов, пока не решено,
// откуда тайлы (Q28). Кружок — область, которую видят исполнители (не точка), метка — район.
import { cx } from './cx.ts';

export interface MapPreviewProps {
  /** Метка в центре области: название района. */
  label: string;
  /** Подпись в углу: «Исполнители видят только эту область». */
  caption?: string;
  /** Что на карте — для скринридера: сама схема декоративна. */
  description: string;
  className?: string;
}

export function MapPreview({ label, caption, description, className }: MapPreviewProps) {
  return (
    <div
      role="img"
      aria-label={description}
      className={cx('map-streets relative h-26 overflow-hidden rounded-card', className)}
    >
      <span className="absolute top-1 right-8 size-24 rounded-full border-2 border-accent/50 bg-accent/14" />
      <span className="absolute top-9 right-20 h-8 translate-x-1/2 whitespace-nowrap rounded-full bg-accent px-2.5 text-[13px] leading-8 font-bold text-accent-ink shadow-pin">
        {label}
      </span>
      {caption && (
        <span className="absolute bottom-2 left-2 inline-flex h-6 items-center rounded-badge bg-surface px-2 text-badge text-text2">
          {caption}
        </span>
      )}
    </div>
  );
}
