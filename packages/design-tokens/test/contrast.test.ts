import { describe, expect, it } from 'vitest';

import source from '../tokens.json' with { type: 'json' };
import { checkContrast, contrastRatio, flatten, luminance } from '../src/contrast.ts';

describe('контраст', () => {
  it('формула WCAG: чёрный на белом 21:1, одинаковые цвета 1:1', () => {
    expect(contrastRatio('#000000', '#FFFFFF')).toBeCloseTo(21, 5);
    expect(contrastRatio('#0B7A5F', '#0B7A5F')).toBe(1);
    expect(luminance('#FFFFFF')).toBe(1);
  });

  it('не принимает цвета не в формате #RRGGBB', () => {
    expect(() => luminance('rgba(0,0,0,.6)')).toThrow();
  });

  it('полупрозрачный цвет смешивается со слоями под ним', () => {
    expect(flatten(['#FFFFFF', 'rgba(0,0,0,.5)'])).toBe('#808080');
    expect(flatten(['#000000', 'rgba(255,255,255,.1)', 'rgba(255,255,255,.1)'])).toBe('#303030');
    expect(flatten(['#0B7A5F'])).toBe('#0B7A5F');
    expect(() => flatten(['rgba(0,0,0,.5)', '#FFFFFF'])).toThrow();
  });

  it.each(checkContrast(source).map((r) => [r.theme, r.fg, r.bg, r]))(
    '%s: %s на %s',
    (_theme, _fg, _bg, result) => {
      expect(result.ratio).toBeGreaterThanOrEqual(result.min);
    },
  );
});
