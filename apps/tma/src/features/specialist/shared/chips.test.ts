import { describe, expect, it } from 'vitest';

import { chipList } from './chips.ts';

const items = ['Адице', 'Грбавица', 'Детелинара', 'Лиман', 'Подбара', 'Телеп', 'Центр'].map(
  (name, index) => ({ id: index + 1, name }),
);
const names = (list: { name: string }[]) => list.map((item) => item.name);

describe('chipList', () => {
  it('puts the chips chosen before first and fills the collapsed list up to count', () => {
    const { ordered, collapsed } = chipList(items, new Set([4, 7]), new Set([4, 7]), 4);

    expect(names(collapsed)).toEqual(['Лиман', 'Центр', 'Адице', 'Грбавица']);
    expect(names(ordered).slice(0, 4)).toEqual(names(collapsed));
    expect(ordered).toHaveLength(items.length);
  });

  it('keeps every chip in place while choosing: unchecked stays, checked filler stays', () => {
    const before = chipList(items, new Set([4]), new Set([4]), 3).collapsed;
    const unchecked = chipList(items, new Set([4]), new Set(), 3).collapsed;
    const checked = chipList(items, new Set([4]), new Set([4, 1]), 3).collapsed;

    expect(names(unchecked)).toEqual(names(before));
    expect(names(checked)).toEqual(names(before));
  });

  it('shows everything chosen even beyond count', () => {
    const { collapsed } = chipList(items, new Set([1, 2, 3]), new Set([1, 2, 3, 7]), 2);

    expect(names(collapsed)).toEqual(['Адице', 'Грбавица', 'Детелинара', 'Центр']);
  });
});
