import { describe, expect, it } from 'vitest';

import { absoluteBase, labelLanguage, mapStyle } from './style.ts';

describe('map style', () => {
  it('loads tiles, glyphs and the sprite of the theme from our assets by absolute URLs', () => {
    const base = absoluteBase('/map', 'https://tma.example/#/jobs/new/when');
    expect(base).toBe('https://tma.example/map/');
    expect(absoluteBase('https://cdn.example/map/20260811/', 'https://tma.example/')).toBe(
      'https://cdn.example/map/20260811/',
    );

    const style = mapStyle({ base, scheme: 'dark', locale: 'ru' });
    expect(style.glyphs).toBe('https://tma.example/map/fonts/{fontstack}/{range}.pbf');
    expect(style.sprite).toBe('https://tma.example/map/sprites/v4/dark');
    expect(style.sources['protomaps']).toMatchObject({
      type: 'vector',
      url: 'pmtiles://https://tma.example/map/novi-sad.pmtiles',
    });
    expect(style.layers.length).toBeGreaterThan(50);
  });

  it('labels: Serbian Cyrillic shows local names as they are, Latin asks for sr-Latn', () => {
    expect(labelLanguage('sr-Cyrl')).toBe('sr');
    expect(labelLanguage('sr-Latn')).toBe('sr-Latn');
    expect(labelLanguage('ru')).toBe('ru');

    const text = (locale: 'sr-Cyrl' | 'sr-Latn') =>
      JSON.stringify(
        mapStyle({ base: 'https://tma.example/map/', scheme: 'light', locale }).layers.find(
          (layer) => layer.id === 'places_locality',
        )?.layout,
      );
    // кириллица — целевая письменность: местное `name` без английской строки сверху
    expect(text('sr-Cyrl')).toContain('["!=",["get","script"],"Cyrillic"]');
    expect(text('sr-Latn')).toContain('"name:sr-Latn"');
  });
});
