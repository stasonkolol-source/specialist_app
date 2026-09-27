// Генерация артефактов из tokens.json: CSS-переменные, блок @theme для Tailwind 4, TS-экспорт, шрифты.
import type { FontFace } from './fonts.ts';
import { FONT_FAMILIES, parseFontsourceCss, renderFontsCss } from './fonts.ts';

export type Theme = 'light' | 'dark';

export interface TypeStyle {
  family: string;
  weight: number;
  size: number;
  line: number;
  tracking?: string;
}

export interface TokenSource {
  color: {
    light: Record<string, string>;
    dark: Record<string, string>;
    static: Record<string, string>;
  };
  avatar: {
    palette: Record<string, { bg: string; ink: string }>;
    size: Record<string, { box: number; font: number }>;
  };
  radius: Record<string, number>;
  font: Record<string, string>;
  type: Record<string, TypeStyle>;
  icon: { stroke: number; default: number; sizes: number[] };
}

const HEADER = 'Сгенерировано scripts/generate.ts из tokens.json — не править руками';

/** Селектор тёмной темы: packages/platform ставит data-theme по colorScheme Telegram. */
export const DARK_SELECTOR = "[data-theme='dark']";

function block(selector: string, lines: string[]): string {
  return `${selector} {\n${lines.map((line) => `  ${line}`).join('\n')}\n}\n`;
}

/** Цвета темы вместе с цветами, общими для обеих тем (тост, аватары). */
export function themeColors(source: TokenSource, theme: Theme): Record<string, string> {
  const avatars = Object.entries(source.avatar.palette).flatMap(([name, { bg, ink }]) => [
    [name, bg],
    [`${name}-ink`, ink],
  ]);
  return { ...source.color[theme], ...source.color.static, ...Object.fromEntries(avatars) };
}

export function renderTokensCss(source: TokenSource): string {
  const shared = [
    ...Object.entries(source.color.static).map(([k, v]) => `--${k}: ${v};`),
    ...Object.entries(source.avatar.palette).flatMap(([k, { bg, ink }]) => [
      `--${k}: ${bg};`,
      `--${k}-ink: ${ink};`,
    ]),
    ...Object.entries(source.radius).map(([k, v]) => `--r-${k}: ${v}px;`),
    ...Object.entries(source.font).map(([k, v]) => `--f-${k}: ${v};`),
  ];
  const light = [
    'color-scheme: light;',
    ...Object.entries(source.color.light).map(([k, v]) => `--${k}: ${v};`),
    ...shared,
  ];
  const dark = [
    'color-scheme: dark;',
    ...Object.entries(source.color.dark).map(([k, v]) => `--${k}: ${v};`),
  ];
  return `/* ${HEADER} */\n${block(':root', light)}${block(DARK_SELECTOR, dark)}`;
}

export function renderThemeCss(source: TokenSource): string {
  const colors = Object.keys(themeColors(source, 'light')).map((k) => `--color-${k}: var(--${k});`);
  const radii = Object.keys(source.radius).map((k) => `--radius-${k}: var(--r-${k});`);
  const fonts = Object.keys(source.font).map((k) => `--font-${k}: var(--f-${k});`);
  const text = Object.entries(source.type).flatMap(([k, s]) => [
    `--text-${k}: ${s.size}px;`,
    `--text-${k}--line-height: ${s.line}px;`,
    `--text-${k}--font-weight: ${s.weight};`,
    ...(s.tracking ? [`--text-${k}--letter-spacing: ${s.tracking};`] : []),
  ]);
  // Инициалы в аватаре: 600, высота строки 1 (.ava в ui.css)
  const avatarText = Object.entries(source.avatar.size).flatMap(([k, s]) => [
    `--text-avatar-${k}: ${s.font}px;`,
    `--text-avatar-${k}--line-height: 1;`,
    `--text-avatar-${k}--font-weight: 600;`,
  ]);
  const lines = [
    // Палитру, радиусы и шкалу Tailwind по умолчанию сбрасываем: в классах — только токены
    '--color-*: initial;',
    ...colors,
    '--radius-*: initial;',
    ...radii,
    '--font-sans: var(--f-ui);',
    ...fonts,
    '--text-*: initial;',
    ...text,
    ...avatarText,
  ];
  return `/* ${HEADER}. Подключать после tailwindcss и tokens.css */\n${block('@theme inline', lines)}`;
}

export function renderTokensTs(source: TokenSource): string {
  const data = {
    color: { light: themeColors(source, 'light'), dark: themeColors(source, 'dark') },
    radius: source.radius,
    font: source.font,
    type: source.type,
    icon: source.icon,
    avatar: source.avatar,
  };
  return `// ${HEADER}\nexport const tokens = ${JSON.stringify(data, null, 2)} as const;\n\nexport type Tokens = typeof tokens;\n`;
}

export interface GeneratedFile {
  path: string;
  content: string;
}

/** CSS начертания @fontsource: `<pkg>/<weight>.css`. */
export type FontCssReader = (pkg: string, weight: number) => string;

export function fontFaces(readFontCss: FontCssReader): FontFace[] {
  return FONT_FAMILIES.flatMap((font) =>
    font.weights.flatMap((w) => parseFontsourceCss(font, w, readFontCss(font.pkg, w))),
  );
}

/** Файлы относительно корня пакета. */
export function renderAll(source: TokenSource, readFontCss: FontCssReader): GeneratedFile[] {
  return [
    { path: 'src/tokens.generated.css', content: renderTokensCss(source) },
    { path: 'src/theme.generated.css', content: renderThemeCss(source) },
    { path: 'src/tokens.generated.ts', content: renderTokensTs(source) },
    { path: 'src/fonts.generated.css', content: renderFontsCss(fontFaces(readFontCss)) },
  ];
}
