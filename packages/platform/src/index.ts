// Порт платформы и адаптеры: tma (Telegram), browser, mock. @tma.js/* разрешён только в этом пакете.
import { isTMA } from '@tma.js/sdk-react';

import { createBrowserPlatform } from './browser.ts';
import { createTmaPlatform } from './tma.ts';
import type { Platform } from './types.ts';

export { createBrowserPlatform } from './browser.ts';
export { useInsets } from './insets.ts';
export type { PreparedMedia, PutResult } from './media.ts';
export {
  MAX_SIDE,
  PREVIEW_SIDE,
  STALL_MS,
  prepareImage,
  webMediaTransport,
  xhrPut,
} from './media.ts';
// mock-клиент Telegram — отдельным входом `@sosed/platform/mock` (тесты, `?platform=mock`): в
// Telegram первый экран его не качает
export type { MockOptions, MockTelegram } from './mock.ts';
export type { BottomButtonProps, ChromeColors } from './react.tsx';
export {
  PlatformProvider,
  applyTheme,
  useBackButton,
  useBackButtonState,
  useBottomButtonState,
  useClosingConfirmation,
  useColorScheme,
  useColorSchemeOverride,
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
