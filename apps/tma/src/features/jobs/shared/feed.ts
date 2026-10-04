// Фильтры ленты S13–S14 (DEVELOPMENT_PLAN 5.3) — в параметрах адреса, как у выдачи S05
// (ADR-0020 §13): переживают «Назад» и открытую заявку, а экран ничего не хранит сам. Здесь же —
// перевод в запрос `GET /jobs`: «когда нужно» становится набором срочностей, бюджет — пара,
// радиус — только с точкой (без неё сервер ответил бы 422). Точка — с точностью ~100 м. «По моим
// подпискам» (5.7) — режим ленты `feed=alerts`, а не фильтр: число на чипе «Фильтры» он не меняет
// и «Сбросить фильтры» его не снимает.
import { rsdToPara } from '@sosed/domain';
import type { FeedQuery } from '@sosed/hooks';

/** Радиусы шторки S14, км; быстрый чип S13 — «До 3 км». */
export const RADII = [1, 3, 5, 10] as const;
export const NEAR_KM = 3;
/** «Когда нужно»: любое время, сегодня, на неделе. */
export const FEED_WHEN = ['today', 'week'] as const;
export type FeedWhen = (typeof FEED_WHEN)[number];
/** «Бюджет от», RSD: шаги второго вида шторки. */
export const BUDGET_STEPS = [2_000, 5_000, 10_000, 20_000, 50_000] as const;
/** Языки заявки — те, что спрашивает мастер S20c (DRAFT_LANGUAGES): не из черновика — адрес
 *  /jobs разбирает первый чанк, а черновик мастера ему не нужен. */
export const FEED_LANGUAGES = ['ru', 'sr', 'en'] as const;
export type FeedLanguage = (typeof FEED_LANGUAGES)[number];

const MAX_LISTED = 20;
const MAX_BUDGET_RSD = 10_000_000;
const COORDINATE_DIGITS = 3;

export interface FeedSearch {
  /** Разделы и услуги каталога: заявки любой из них, с подкатегориями. */
  categories?: number[];
  /** Радиус от точки, км. */
  near?: number;
  lat?: number;
  lon?: number;
  when?: FeedWhen;
  urgent?: true;
  photos?: true;
  /** Бюджет «от», RSD — как выбирает человек; в API уходит в пара. */
  budget?: number;
  langs?: FeedLanguage[];
  /** «По моим подпискам»: заявки, подходящие включённым подпискам (только вошедшему). */
  alerts?: true;
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

/** validateSearch S13: известные значения в допустимых пределах, остальное отбрасывается. */
export function feedSearch(search: Record<string, unknown>): FeedSearch {
  const lat = coordinate(search.lat, 90);
  const lon = coordinate(search.lon, 180);
  const point = lat !== undefined && lon !== undefined;
  const near = integer(search.near, 1, 50);
  const result: FeedSearch = {
    categories: listOf(search.categories, (item) => integer(item, 1, Number.MAX_SAFE_INTEGER)),
    near: point ? near : undefined,
    lat: point ? lat : undefined,
    lon: point ? lon : undefined,
    when: oneOf(FEED_WHEN, search.when) ? search.when : undefined,
    urgent: flag(search.urgent),
    photos: flag(search.photos),
    budget: integer(search.budget, 1, MAX_BUDGET_RSD),
    langs: listOf(search.langs, (item) => (oneOf(FEED_LANGUAGES, item) ? item : undefined)),
    alerts: flag(search.alerts),
  };
  return Object.fromEntries(
    Object.entries(result).filter(([, value]) => value !== undefined),
  ) as FeedSearch;
}

/** Срочности для «когда нужно»: «срочные» — только asap, «сегодня» — ещё и today. */
export function urgencies(search: FeedSearch): FeedQuery['urgency'] {
  if (search.urgent) return ['asap'];
  if (search.when === 'today') return ['asap', 'today'];
  if (search.when === 'week') return ['asap', 'today', 'this_week'];
  return undefined;
}

/** Точка уходит и без радиуса: тогда она нужна только для «≈ 1,2 км» в карточках. */
export function toFeedQuery(search: FeedSearch, cityId: number): FeedQuery {
  const point = search.lat !== undefined && search.lon !== undefined;
  return {
    city_id: cityId,
    category: search.categories,
    lat: point ? search.lat : undefined,
    lon: point ? search.lon : undefined,
    radius_km: point ? search.near : undefined,
    urgency: urgencies(search),
    budget_from: search.budget !== undefined ? rsdToPara(search.budget) : undefined,
    lang: search.langs,
    has_photos: search.photos,
    feed: search.alerts ? 'alerts' : undefined,
  };
}

/** Сколько фильтров выбрано — число на чипе «Фильтры». */
export function activeFilters(search: FeedSearch): number {
  return [
    (search.categories?.length ?? 0) > 0,
    search.near !== undefined,
    search.when !== undefined,
    search.urgent === true,
    search.photos === true,
    search.budget !== undefined,
    (search.langs?.length ?? 0) > 0,
  ].filter(Boolean).length;
}

/** «Сбросить»: точка остаётся — второй раз местоположение не спрашиваем; режим «по моим
 *  подпискам» — тоже: это не фильтр. */
export function withoutFilters(search: FeedSearch): FeedSearch {
  const point =
    search.lat !== undefined && search.lon !== undefined
      ? { lat: search.lat, lon: search.lon }
      : {};
  return search.alerts ? { ...point, alerts: true } : point;
}

export function toggle<T>(list: readonly T[] | undefined, value: T): T[] | undefined {
  const next = list?.includes(value)
    ? list.filter((item) => item !== value)
    : [...(list ?? []), value];
  return next.length > 0 ? next : undefined;
}
