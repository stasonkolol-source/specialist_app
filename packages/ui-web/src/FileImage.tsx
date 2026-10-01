// Локальный файл картинкой (превью загрузки): общий для Photo и Avatar. Отдельным модулем — Avatar
// первого экрана не тянет за собой Photo с декодером ThumbHash.
import { useCallback } from 'react';

/** blob: URL создаётся при монтировании и отзывается при снятии: без утечки памяти на превью. */
export function FileImage({ file, alt }: { file: Blob; alt: string }) {
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
