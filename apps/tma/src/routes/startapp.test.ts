import golden from '@sosed/links/golden.json' with { type: 'json' };
import { describe, expect, it } from 'vitest';

import { startTarget } from './startapp.ts';

describe('startTarget', () => {
  it('is null without a deep link', () => {
    expect(startTarget(null)).toBeNull();
    expect(startTarget('')).toBeNull();
  });

  it('opens home for `h` and for targets whose screens come in later steps', () => {
    expect(startTarget('h')).toBe('/');
    expect(startTarget('h_rAB12CD')).toBe('/');
    // S08 (4.5), S15 (5.3), S26 (6.2), S30 (6.4) — до своих шагов на главную
    for (const { param, link } of golden.valid) {
      if (link.type !== 'legal') expect(startTarget(param)).toBe('/');
    }
  });

  it('opens the S48 tab for links to the rules and the privacy policy (bot /terms, /privacy)', () => {
    expect(startTarget('l_terms')).toBe('/legal/terms');
    expect(startTarget('l_privacy')).toBe('/legal/privacy');
    expect(startTarget('l_privacy_rAB12CD')).toBe('/legal/privacy');
  });

  it('opens home for broken and foreign codes', () => {
    for (const param of golden.invalid.filter(Boolean)) expect(startTarget(param)).toBe('/');
  });
});
