// Контраст по WCAG 2.2: текст ≥ 4,5:1, границы полей и другие нетекстовые элементы ≥ 3:1.
import type { Theme, TokenSource } from './render.ts';
import { themeColors } from './render.ts';

export interface ContrastPair {
  fg: string;
  bg: string;
  /** bg полупрозрачный — слои под ним, снизу вверх: контраст считается с тем, что видно на экране. */
  over?: readonly string[];
  min: number;
  /** Где в ui.css встречается пара. */
  use: string;
}

const TEXT = 4.5;
const NON_TEXT = 3;

const avatarPairs = [1, 2, 3, 4, 5].map((n) => ({
  fg: `av${n}-ink`,
  bg: `av${n}`,
  min: TEXT,
  use: `.ava.av${n}, .tile .row-ic.av${n}`,
}));

export const PAIRS: readonly ContrastPair[] = [
  { fg: 'text', bg: 'bg', min: TEXT, use: 'основной текст на фоне экрана' },
  { fg: 'text', bg: 'bg2', min: TEXT, use: '.scr, .ibtn' },
  { fg: 'text', bg: 'surface', min: TEXT, use: '.card, .row, .chip, .inp' },
  { fg: 'text2', bg: 'bg', min: TEXT, use: '.tab, .tgh-t span' },
  { fg: 'text2', bg: 'bg2', min: TEXT, use: '.cap на фоне экрана, .bdg.mute' },
  { fg: 'text2', bg: 'surface', min: TEXT, use: '.cap, .sp-meta, .hint в карточке' },
  { fg: 'bg', bg: 'text', min: TEXT, use: '.chip.on, .bdg.pro' },
  { fg: 'accent', bg: 'bg', min: TEXT, use: '.tab.on, .tgh-btn, a' },
  { fg: 'accent', bg: 'bg2', min: TEXT, use: '.link на фоне экрана' },
  { fg: 'accent', bg: 'surface', min: TEXT, use: '.link в карточке' },
  { fg: 'accent-ink', bg: 'accent', min: TEXT, use: '.btn.pri, .mbtn, .chip .n, .bub.out' },
  { fg: 'accent-soft-ink', bg: 'accent-soft', min: TEXT, use: '.btn.sec, .bdg.ok, .bnr.ok' },
  { fg: 'urgent-ink', bg: 'urgent', min: TEXT, use: '.tab .cnt' },
  { fg: 'urgent-soft-ink', bg: 'urgent-soft', min: TEXT, use: '.bdg.urg, .bnr.warn' },
  { fg: 'info-ink', bg: 'info-soft', min: TEXT, use: '.bdg.info, .bnr.info' },
  { fg: 'danger', bg: 'danger-soft', min: TEXT, use: '.btn.dng, .bdg.dng, .bnr.dng' },
  { fg: 'danger', bg: 'bg', min: TEXT, use: '.err' },
  { fg: 'danger', bg: 'bg2', min: TEXT, use: '.err на фоне экрана' },
  { fg: 'danger', bg: 'surface', min: TEXT, use: '.err в карточке, .ibtn.on' },
  { fg: 'danger-ink', bg: 'danger', min: TEXT, use: '.mbtn.dng' },
  { fg: 'toast-ink', bg: 'toast', min: TEXT, use: '.toast' },
  ...avatarPairs,
  { fg: 'field', bg: 'surface', min: NON_TEXT, use: 'граница .inp, .radio, .chk' },
  { fg: 'field', bg: 'bg', min: NON_TEXT, use: 'граница .inp на фоне экрана' },
  // Дорожка .seg и выбранный сегмент полупрозрачные: считаем поверх того, на чём стоит контрол, —
  // экран (bg2), шторка (bg), карточка (surface)
  ...['bg2', 'bg', 'surface'].flatMap((under) => [
    { fg: 'text2', bg: 'seg-track', over: [under], min: TEXT, use: `.seg на ${under}` },
    {
      fg: 'text',
      bg: 'seg-on',
      over: [under, 'seg-track'],
      min: TEXT,
      use: `.seg>.on на ${under}`,
    },
  ]),
];

function channel(value: number): number {
  const c = value / 255;
  return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
}

export function luminance(hex: string): number {
  const match = /^#([0-9a-f]{6})$/i.exec(hex);
  if (!match?.[1]) throw new Error(`Ожидался цвет #RRGGBB, получено «${hex}»`);
  const n = Number.parseInt(match[1], 16);
  return 0.2126 * channel(n >> 16) + 0.7152 * channel((n >> 8) & 0xff) + 0.0722 * channel(n & 0xff);
}

interface Rgba {
  r: number;
  g: number;
  b: number;
  a: number;
}

function parseColor(value: string): Rgba {
  const hex = /^#([0-9a-f]{6})$/i.exec(value);
  if (hex?.[1]) {
    const n = Number.parseInt(hex[1], 16);
    return { r: n >> 16, g: (n >> 8) & 0xff, b: n & 0xff, a: 1 };
  }
  const rgba = /^rgba\((\d+),(\d+),(\d+),([\d.]+)\)$/.exec(value.replace(/\s+/g, ''));
  if (rgba) {
    const [, r, g, b, a] = rgba.map(Number) as [number, number, number, number, number];
    return { r, g, b, a };
  }
  throw new Error(`Ожидался цвет #RRGGBB или rgba(), получено «${value}»`);
}

/** Слои снизу вверх → непрозрачный #RRGGBB: каким полупрозрачный цвет выходит на экране. */
export function flatten(layers: readonly string[]): string {
  const [base, ...rest] = layers.map(parseColor);
  if (!base || base.a !== 1) {
    throw new Error(`Нижний слой должен быть непрозрачным: ${layers.join(' + ')}`);
  }
  const mix = (top: number, under: number, a: number) => top * a + under * (1 - a);
  const out = rest.reduce(
    (under, top) => ({
      r: mix(top.r, under.r, top.a),
      g: mix(top.g, under.g, top.a),
      b: mix(top.b, under.b, top.a),
      a: 1,
    }),
    base,
  );
  const hex = (c: number) => Math.round(c).toString(16).padStart(2, '0');
  return `#${hex(out.r)}${hex(out.g)}${hex(out.b)}`.toUpperCase();
}

export function contrastRatio(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x) as [number, number];
  return (hi + 0.05) / (lo + 0.05);
}

export interface ContrastResult extends ContrastPair {
  theme: Theme;
  ratio: number;
  ok: boolean;
}

export function checkContrast(source: TokenSource): ContrastResult[] {
  const themes: Theme[] = ['light', 'dark'];
  return themes.flatMap((theme) => {
    const colors = themeColors(source, theme);
    const token = (name: string) => {
      const value = colors[name];
      if (!value) throw new Error(`Нет токена ${name} (${theme})`);
      return value;
    };
    return PAIRS.map((pair) => {
      const bg = flatten([...(pair.over ?? []), pair.bg].map(token));
      const ratio = contrastRatio(token(pair.fg), bg);
      return { ...pair, theme, ratio, ok: ratio >= pair.min };
    });
  });
}
