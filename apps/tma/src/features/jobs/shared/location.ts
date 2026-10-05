// Точка исполнителя для радиуса ленты S13–S14: спрашивает Telegram (LocationManager), в браузере —
// geolocation. Отказ или недоступность — null: экран скажет и покажет ленту без радиуса. В адрес
// попадает с точностью ~100 м, как у каталога (фичи не импортируют друг друга).
import { usePlatform } from '@sosed/platform';
import { useCallback } from 'react';

const DIGITS = 3;

export interface ViewerPoint {
  lat: number;
  lon: number;
}

export function useLocate(): () => Promise<ViewerPoint | null> {
  const platform = usePlatform();
  return useCallback(async () => {
    const found = await platform.location.get();
    return found
      ? { lat: Number(found.lat.toFixed(DIGITS)), lon: Number(found.lon.toFixed(DIGITS)) }
      : null;
  }, [platform]);
}
