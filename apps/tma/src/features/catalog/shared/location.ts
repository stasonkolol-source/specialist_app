// Точка клиента для «Ближе» и «До 3 км» (S05, S06): спрашивает Telegram (LocationManager), в
// браузере — geolocation. Отказ или недоступность — null: экран скажет и покажет выдачу без точки.
// В адрес попадает с точностью ~100 м: точнее выдаче не нужно, а адресом делятся.
import { usePlatform } from '@sosed/platform';
import { useCallback } from 'react';

const DIGITS = 3;

export interface ClientPoint {
  lat: number;
  lon: number;
}

export function useLocate(): () => Promise<ClientPoint | null> {
  const platform = usePlatform();
  return useCallback(async () => {
    const found = await platform.location.request().catch(() => null);
    return found
      ? {
          lat: Number(found.latitude.toFixed(DIGITS)),
          lon: Number(found.longitude.toFixed(DIGITS)),
        }
      : null;
  }, [platform]);
}
