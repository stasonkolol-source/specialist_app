// Токены совпадают с утверждённым design/ui.css: переменные тем, палитра аватаров, радиусы, типошкала, размеры.
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

import source from '../tokens.json' with { type: 'json' };
import type { Declarations } from '../scripts/css.ts';
import { customProperties, normalizeValue, parseRules } from '../scripts/css.ts';
import type { TypeStyle } from '../src/render.ts';
import { DARK_SELECTOR } from '../src/render.ts';

const read = (rel: string) => readFileSync(new URL(rel, import.meta.url), 'utf8');
const ui = parseRules(read('../../../design/ui.css'));
const generated = parseRules(read('../src/tokens.generated.css'));

function rule(selector: string): Declarations {
  const decls = ui.get(selector);
  if (!decls) throw new Error(`В ui.css нет правила ${selector}`);
  return decls;
}

function px(value: string | undefined): number {
  const n = Number.parseFloat(value ?? '');
  if (Number.isNaN(n)) throw new Error(`Ожидалось значение в px, получено «${value}»`);
  return n;
}

const norm = (vars: Record<string, string>) =>
  Object.fromEntries(Object.entries(vars).map(([k, v]) => [k, normalizeValue(v)]));

describe('переменные тем', () => {
  const uiLight = customProperties(rule(':root'));
  const uiDark = customProperties(rule('.theme-dark'));
  const genLight = customProperties(generated.get(':root'));
  const genDark = customProperties(generated.get(DARK_SELECTOR));

  it('светлая тема совпадает с :root из ui.css', () => {
    const picked = Object.fromEntries(Object.keys(uiLight).map((k) => [k, genLight[k] ?? '']));
    expect(norm(picked)).toEqual(norm(uiLight));
  });

  it('тёмная тема совпадает с .theme-dark из ui.css', () => {
    const picked = Object.fromEntries(Object.keys(uiDark).map((k) => [k, genDark[k] ?? '']));
    expect(norm(picked)).toEqual(norm(uiDark));
  });

  it('сверх ui.css — только задокументированные добавления', () => {
    const extraLight = Object.keys(genLight).filter((k) => !(k in uiLight));
    const extraDark = Object.keys(genDark).filter((k) => !(k in uiDark));
    const radii = ['btn-sm', 'chip', 'badge', 'banner', 'sheet', 'photo'].map((r) => `r-${r}`);
    const avatars = [1, 2, 3, 4, 5].flatMap((n) => [`av${n}`, `av${n}-ink`]);
    expect(extraLight.sort()).toEqual(
      ['danger-ink', 'toast', 'toast-ink', ...avatars, ...radii].sort(),
    );
    expect(extraDark).toEqual(['danger-ink']);
  });

  it('danger-ink светлой темы — цвет текста .mbtn.dng', () => {
    expect(normalizeValue(source.color.light['danger-ink'])).toBe(
      normalizeValue(rule('.mbtn.dng').color ?? ''),
    );
  });

  it('тёмная тема переопределяет все цвета светлой', () => {
    expect(Object.keys(source.color.dark)).toEqual(Object.keys(source.color.light));
  });
});

describe('цвета компонентов', () => {
  it.each([1, 2, 3, 4, 5])('палитра аватара av%i', (n) => {
    const decls = rule(`.av${n}`);
    const token = source.avatar.palette[`av${n}` as keyof typeof source.avatar.palette];
    expect(normalizeValue(token.bg)).toBe(normalizeValue(decls.background ?? ''));
    expect(normalizeValue(token.ink)).toBe(normalizeValue(decls.color ?? ''));
  });

  it('тост', () => {
    const decls = rule('.toast');
    expect(normalizeValue(source.color.static.toast)).toBe(normalizeValue(decls.background ?? ''));
    expect(normalizeValue(source.color.static['toast-ink'])).toBe(
      normalizeValue(decls.color ?? ''),
    );
  });
});

describe('радиусы', () => {
  it.each([
    ['card', ':root', '--r-card'],
    ['field', ':root', '--r-field'],
    ['btn', ':root', '--r-btn'],
    ['btn-sm', '.btn.sm', 'border-radius'],
    ['chip', '.chip', 'border-radius'],
    ['badge', '.bdg', 'border-radius'],
    ['banner', '.bnr', 'border-radius'],
    ['sheet', '.sheet', 'border-radius'],
    ['photo', '.ph', 'border-radius'],
  ])('%s = %s { %s }', (name, selector, prop) => {
    expect(source.radius[name as keyof typeof source.radius]).toBe(px(rule(selector)[prop]));
  });
});

type Parsed = Required<Pick<TypeStyle, 'family' | 'weight' | 'size' | 'line'>> & {
  tracking?: number;
};

function typeOf(selector: string, base?: Parsed): Parsed {
  const decls = rule(selector);
  const tracking = decls['letter-spacing']
    ? Number.parseFloat(decls['letter-spacing'])
    : base?.tracking;
  const font = decls.font && /^(\d+) (\d+)px\/(\d+)px var\(--f-(\w+)\)$/.exec(decls.font);
  if (font) {
    const [, weight, size, line, family] = font;
    return {
      family: family ?? '',
      weight: Number(weight),
      size: Number(size),
      line: Number(line),
      tracking,
    };
  }
  return {
    family: base?.family ?? 'ui',
    weight: decls['font-weight'] ? Number(decls['font-weight']) : (base?.weight ?? 400),
    size: decls['font-size'] ? px(decls['font-size']) : (base?.size ?? 0),
    line: decls['line-height'] ? px(decls['line-height']) : (base?.line ?? 0),
    tracking,
  };
}

describe('типошкала', () => {
  const h1 = typeOf('.h1');
  const price = typeOf('.price');
  const cases: [string, Parsed][] = [
    ['h1', h1],
    ['h1-xl', typeOf('.h1.xl', h1)],
    ['h2', typeOf('.h2')],
    ['h3', typeOf('.h3')],
    ['title', typeOf('.sp-name')],
    ['body', typeOf('.scr')],
    ['input', typeOf('.inp')],
    ['button', typeOf('.btn')],
    ['main-button', typeOf('.mbtn')],
    ['sm', typeOf('.sm')],
    ['cap', typeOf('.cap')],
    ['section', typeOf('.sec-t')],
    ['badge', typeOf('.bdg')],
    ['tab', typeOf('.tab')],
    ['price', price],
    ['price-lg', typeOf('.price.lg', price)],
  ];

  it('в tokens.json нет стилей без сверки', () => {
    expect(Object.keys(source.type).sort()).toEqual(cases.map(([name]) => name).sort());
  });

  it.each(cases)('%s', (name, expected) => {
    const token: TypeStyle = source.type[name as keyof typeof source.type];
    const tracking = token.tracking ? Number.parseFloat(token.tracking) : undefined;
    expect({ ...token, tracking }).toEqual(expected);
  });

  it('заголовок задачи совпадает с именем специалиста', () => {
    expect(typeOf('.job-t')).toEqual(typeOf('.sp-name'));
  });
});

describe('размеры', () => {
  it.each([
    ['xs', '.ava.xs'],
    ['sm', '.ava.sm'],
    ['md', '.ava'],
    ['lg', '.ava.lg'],
    ['xl', '.ava.xl'],
  ])('аватар %s', (size, selector) => {
    const decls = rule(selector);
    const token = source.avatar.size[size as keyof typeof source.avatar.size];
    expect(token.box).toBe(px(decls.width));
    // у .ava размер шрифта в шорткате font: 600 17px/1 …
    expect(token.font).toBe(px(decls['font-size'] ?? /(\d+)px/.exec(decls.font ?? '')?.[1]));
  });

  it('иконки', () => {
    expect(source.icon.default).toBe(px(rule('.ic').width));
    expect(source.icon.stroke).toBe(Number(rule('.ic')['stroke-width']));
    const sizes = [16, 24, 28, 32].map((s) => px(rule(`.ic.i${s}`).width));
    expect(source.icon.sizes).toEqual(
      [16, 20, 24, 28, 32, px(rule('.stars .ic').width)].sort((a, b) => a - b),
    );
    expect(sizes).toEqual([16, 24, 28, 32]);
  });
});
