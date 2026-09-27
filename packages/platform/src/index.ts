// Порт платформы и адаптеры: tma (Telegram), browser, mock. @tma.js/* разрешён только в этом пакете.
import { isTMA } from '@tma.js/sdk-react';

import { createBrowserPlatform } from './browser.ts';
import { createTmaPlatform } from './tma.ts';
import type { Platform } from './types.ts';

export { createBrowserPlatform } from './browser.ts';
export type { MockOptions, MockTelegram } from './mock.ts';
export { MOCK_THEMES, MOCK_USER, createMockPlatform } from './mock.ts';
export type { BottomButtonProps, ChromeColors } from './react.tsx';
export {
  PlatformProvider,
  useBackButton,
  useBottomButtonState,
  useClosingConfirmation,
  useColorScheme,
  useMainButton,
  usePlatform,
  useSecondaryButton,
  useThemeSync,
} from './react.tsx';
export { createTmaPlatform } from './tma.ts';
export type * from './types.ts';
export { MIN_VERSION, capabilitiesFor, compareVersions, isVersionAtLeast } from './version.ts';

/** Точка сборки: внутри Telegram — адаптер tma, иначе — браузер. */
export function createPlatform(): Platform {
  return isTMA() ? createTmaPlatform() : createBrowserPlatform();
}
