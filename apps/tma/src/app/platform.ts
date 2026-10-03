// Адаптер платформы — синглтон точки сборки (ADR-0020 §13): в Telegram — адаптер tma, вне его —
// браузер. `?platform=mock` — mock-клиент Telegram (app/mockPlatform.ts) для разработки и e2e: он
// грузится своим чанком, первый экран в Telegram его не качает.
import type { Platform } from '@sosed/platform';
import { createPlatform } from '@sosed/platform';

export function selectPlatform(
  search: string = window.location.search,
): Platform | Promise<Platform> {
  const params = new URLSearchParams(search);
  if (params.get('platform') !== 'mock') return createPlatform();
  return import('./mockPlatform.ts').then((module) => module.mockPlatform(params));
}
