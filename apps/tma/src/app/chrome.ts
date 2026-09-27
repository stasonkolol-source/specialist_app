// Цвета шапки, фона и нижней панели клиента Telegram — из токенов утверждённого ui.css. Ставит
// их точка сборки (App.tsx) до первого экрана, вместе с `data-theme`.
import { tokens } from '@sosed/design-tokens';
import type { ChromeColors, ColorScheme } from '@sosed/platform';

const chrome = (scheme: ColorScheme): ChromeColors => ({
  header: tokens.color[scheme].bg,
  background: tokens.color[scheme].bg2,
  bottomBar: tokens.color[scheme].bg,
});

export const CHROME: Record<ColorScheme, ChromeColors> = {
  light: chrome('light'),
  dark: chrome('dark'),
};
