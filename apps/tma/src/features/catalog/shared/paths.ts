// Адреса каталога S04–S06 (DEVELOPMENT_PLAN 4.4). Текст, фильтры и порядок выдачи — в параметрах
// адреса (ADR-0020 §13): переживают «Назад», ими можно поделиться, а экран ничего не хранит сам.
export const CATALOG_PATHS = {
  categories: '/catalog',
  results: '/catalog/results',
} as const;

/** Порядок выдачи на S06 — как на макете; «по цене» сервер умеет, в шторке его нет. */
export const RESULT_SORTS = ['relevance', 'distance', 'rating'] as const;
export type ResultSort = (typeof RESULT_SORTS)[number];
/** Языки общения в профиле специалиста (specialists.Language). */
export const LANGUAGES = ['ru', 'sr', 'en', 'uk'] as const;
export type Language = (typeof LANGUAGES)[number];
export const WORK_MODES = ['at_client', 'at_own_place', 'remote'] as const;
export type WorkMode = (typeof WORK_MODES)[number];
/** Быстрый чип «До 3 км» на S05. */
export const NEAR_KM = 3;
const MAX_LISTED = 20;
const MAX_QUERY = 100;
const MAX_PRICE_RSD = 10_000_000;
/** Точка клиента в адресе — с точностью ~100 м: точнее для выдачи не нужно. */
const COORDINATE_DIGITS = 3;

export interface ResultsSearch {
  q?: string;
  category?: number;
  sort?: ResultSort;
  districts?: number[];
  /** Цена «до» в RSD — как вводит человек; в API уходит в пара. */
  price?: number;
  langs?: Language[];
  modes?: WorkMode[];
  today?: true;
  reviews?: true;
  /** Радиус от точки клиента, км (чип «До 3 км»). */
  near?: number;
  lat?: number;
  lon?: number;
  kind?: 'casual';
  /** «Срочно» с Главной: доступные сегодня — выше. */
  urgent?: true;
}

function integer(value: unknown, min: number, max: number): number | undefined {
  const number = typeof value === 'string' ? Number(value) : value;
  return typeof number === 'number' && Number.isInteger(number) && number >= min && number <= max
    ? number
    : undefined;
}

function coordinate(value: unknown, limit: number): number | undefined {
  const number = typeof value === 'string' ? Number(value) : value;
  if (typeof number !== 'number' || !Number.isFinite(number) || Math.abs(number) > limit) {
    return undefined;
  }
  return Number(number.toFixed(COORDINATE_DIGITS));
}

function oneOf<T extends string>(allowed: readonly T[], value: unknown): value is T {
  return typeof value === 'string' && (allowed as readonly string[]).includes(value);
}

function listOf<T>(value: unknown, pick: (item: unknown) => T | undefined): T[] | undefined {
  if (!Array.isArray(value)) return undefined;
  const items = [...new Set(value.map(pick).filter((item) => item !== undefined))];
  return items.length > 0 ? items.slice(0, MAX_LISTED) : undefined;
}

function flag(value: unknown): true | undefined {
  return value === true || value === 'true' ? true : undefined;
}

/** validateSearch S05: известные значения в допустимых пределах, остальное отбрасывается. */
export function resultsSearch(search: Record<string, unknown>): ResultsSearch {
  const q = typeof search.q === 'string' ? search.q.trim().slice(0, MAX_QUERY) : '';
  const lat = coordinate(search.lat, 90);
  const lon = coordinate(search.lon, 180);
  const point = lat !== undefined && lon !== undefined;
  const result: ResultsSearch = {
    q: q || undefined,
    category: integer(search.category, 1, Number.MAX_SAFE_INTEGER),
    sort: oneOf(RESULT_SORTS, search.sort) && search.sort !== 'relevance' ? search.sort : undefined,
    districts: listOf(search.districts, (item) => integer(item, 1, Number.MAX_SAFE_INTEGER)),
    price: integer(search.price, 1, MAX_PRICE_RSD),
    langs: listOf(search.langs, (item) => (oneOf(LANGUAGES, item) ? item : undefined)),
    modes: listOf(search.modes, (item) => (oneOf(WORK_MODES, item) ? item : undefined)),
    today: flag(search.today),
    reviews: flag(search.reviews),
    near: point ? integer(search.near, 1, 50) : undefined,
    lat: point ? lat : undefined,
    lon: point ? lon : undefined,
    kind: search.kind === 'casual' ? 'casual' : undefined,
    urgent: flag(search.urgent),
  };
  if (result.sort === 'distance' && !point) delete result.sort;
  return Object.fromEntries(
    Object.entries(result).filter(([, value]) => value !== undefined),
  ) as ResultsSearch;
}
