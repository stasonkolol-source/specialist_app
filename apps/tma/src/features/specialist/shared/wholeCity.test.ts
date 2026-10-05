import { describe, expect, it } from 'vitest';

import { MAX_AREAS, coversCity, wholeCityAvailable, wholeCityDefault } from './wholeCity.ts';

const districts = [{ id: 11 }, { id: 12 }, { id: 13 }];

describe('«Весь город»', () => {
  it('по умолчанию включён у выезжающего специалиста без районов', () => {
    expect(wholeCityDefault(districts, [], true)).toBe(true);
    expect(wholeCityDefault(districts, [], false)).toBe(false);
  });

  it('у профиля с районами — включён, только если отмечены все', () => {
    expect(wholeCityDefault(districts, [13, 11, 12], true)).toBe(true);
    expect(wholeCityDefault(districts, [11, 12], true)).toBe(false);
    expect(wholeCityDefault(districts, [11, 12, 13], false)).toBe(true);
  });

  it('недоступен без районов и когда все районы не поместятся в профиль', () => {
    const many = Array.from({ length: MAX_AREAS + 1 }, (_, index) => ({ id: index + 1 }));
    expect(wholeCityAvailable([])).toBe(false);
    expect(wholeCityAvailable(many)).toBe(false);
    expect(wholeCityDefault(many, [], true)).toBe(false);
    expect(coversCity([], [])).toBe(false);
  });
});
