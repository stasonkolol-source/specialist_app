import type { CategoryOut, DistrictOut } from '@sosed/api-client';
import { describe, expect, it } from 'vitest';

import { leafCategories, selectableDistricts } from './categories.ts';

const category = (id: number, name: string, children: CategoryOut[] = []): CategoryOut => ({
  id,
  slug: `c${id}`,
  name,
  icon: null,
  price_hint: null,
  tags: [],
  children,
});

const district = (id: number, name: string, kind: DistrictOut['kind']): DistrictOut => ({
  id,
  slug: `d${id}`,
  name,
  kind,
  parent_id: kind === 'neighborhood' ? 1 : null,
  center: { lat: 45.25, lon: 19.84 },
});

describe('leafCategories', () => {
  it('flattens the tree to leaves in catalog order', () => {
    const tree = [
      category(1, 'Мастер на час', [category(11, 'Электрика'), category(12, 'Сантехника')]),
      category(2, 'Уборка', [category(21, 'Генеральная уборка')]),
      category(3, 'Без подразделов'),
    ];

    expect(leafCategories(tree).map((c) => c.name)).toEqual([
      'Электрика',
      'Сантехника',
      'Генеральная уборка',
      'Без подразделов',
    ]);
  });
});

describe('selectableDistricts', () => {
  it('offers neighborhoods without the whole-city municipality, alphabetically', () => {
    const districts = [
      district(1, 'Нови-Сад', 'municipality'),
      district(2, 'Адице', 'neighborhood'),
      district(3, 'Авиятичарско населье', 'neighborhood'),
      district(4, 'Грбавица', 'neighborhood'),
    ];

    expect(selectableDistricts(districts, 'ru').map((d) => d.name)).toEqual([
      'Авиятичарско населье',
      'Адице',
      'Грбавица',
    ]);
  });
});
