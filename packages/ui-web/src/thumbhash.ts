// ThumbHash с сервера (base64) → размытое превью фоном рамки, пока грузится фото (шаг 2.2a).
import type { CSSProperties } from 'react';
import { useMemo } from 'react';
import { thumbHashToDataURL } from 'thumbhash';

/** ThumbHash → PNG data URL фоном рамки; битый хэш — без превью. */
export function usePlaceholder(placeholder: string | null | undefined): CSSProperties | undefined {
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
