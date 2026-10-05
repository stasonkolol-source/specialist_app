// Стиль карты: подложка Protomaps v4 (@protomaps/basemaps 5.x) из наших ассетов — тайлы PMTiles,
// глифы и спрайт по базе VITE_MAP_ASSETS_URL (scripts/map/README.md). Светлая или тёмная — по теме
// приложения, подписи — на языке интерфейса.
import type { Locale } from '@sosed/i18n';
import type { ColorScheme } from '@sosed/platform';
import { language_script_pairs, layers, namedFlavor } from '@protomaps/basemaps';
import type { StyleSpecification } from 'maplibre-gl';

const SOURCE = 'protomaps';

/** Рамка тайлов: город с запасом 5 км (provenance.json, `inputs.bbox`) — за ней карты нет. */
export const MAP_BOUNDS: [[number, number], [number, number]] = [
  [19.5563, 45.1048],
  [19.9956, 45.3851],
];

// В схеме Protomaps нет сербского: язык без пары считается латиницей, и местные кириллические
// подписи получили бы сверху строку `name:en`. Пара «sr — кириллица» — их же точка расширения:
// массив экспортирован, и его читает генератор подписей.
if (!language_script_pairs.some((pair) => pair.lang === 'sr')) {
  language_script_pairs.push({ lang: 'sr', full_name: 'Serbian', script: 'Cyrillic' });
}

/** Язык подписей. sr-Cyrl — местные кириллические названия; sr-Latn — `name:sr-Latn`, которого в
 *  тайлах пока нет: у районов и города — латинское `name:en` и под ним местное, улицы — местные;
 *  ru — русские названия, где они есть, иначе местные. */
export function labelLanguage(locale: Locale): string {
  return locale === 'sr-Cyrl' ? 'sr' : locale;
}

/** Абсолютный адрес базы: тайлы, глифы и спрайт качают и воркеры MapLibre, а у них нет адреса
 *  страницы, от которого считать путь `/map`. */
export function absoluteBase(base: string, page: string): string {
  return new URL(base.endsWith('/') ? base : `${base}/`, page).href;
}

export function mapStyle({
  base,
  scheme,
  locale,
}: {
  /** Абсолютная база ассетов со слешем в конце (`absoluteBase`). */
  base: string;
  scheme: ColorScheme;
  locale: Locale;
}): StyleSpecification {
  return {
    version: 8,
    glyphs: `${base}fonts/{fontstack}/{range}.pbf`,
    sprite: `${base}sprites/v4/${scheme}`,
    sources: {
      [SOURCE]: {
        type: 'vector',
        url: `pmtiles://${base}novi-sad.pmtiles`,
        // подпись обязательна (ODbL): её рисует сам экран под картой, контрол MapLibre выключен
        attribution: '© OpenStreetMap, Protomaps',
      },
    },
    layers: layers(SOURCE, namedFlavor(scheme), { lang: labelLanguage(locale) }),
  };
}
