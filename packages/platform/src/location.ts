// Геолокация браузера — для веб-оболочки и для старых клиентов Telegram без LocationManager
// (Bot API < 8.0): их WebView обычно умеет navigator.geolocation и сам спросит разрешение.
import type { LocationPoint } from './types.ts';

/** Сколько ждать точку: дольше человек уже выбирает район из списка сам. */
export const LOCATION_TIMEOUT_MS = 10_000;
/** Точка минутной давности годится: район за минуту не меняется, а ответ — сразу. */
const LOCATION_MAX_AGE_MS = 60_000;

/** Высокая точность не нужна (район, радиус) — без неё быстрее и без GPS. Нет API, отказ,
 *  тайм-аут — `null`. */
export function browserLocation(): Promise<LocationPoint | null> {
  return new Promise((resolve) => {
    const geolocation = typeof navigator === 'undefined' ? undefined : navigator.geolocation;
    if (!geolocation) {
      resolve(null);
      return;
    }
    geolocation.getCurrentPosition(
      (position) => resolve({ lat: position.coords.latitude, lon: position.coords.longitude }),
      () => resolve(null),
      {
        enableHighAccuracy: false,
        timeout: LOCATION_TIMEOUT_MS,
        maximumAge: LOCATION_MAX_AGE_MS,
      },
    );
  });
}
