// Выдача специалистов S05 (DEVELOPMENT_PLAN 4.2, 4.4): страницы по курсору, «Показать N» в шторке
// S06 и числа в дереве категорий S04; на Главной S03 (4.8) — подсказки при вводе и «Свободны
// сегодня рядом». Район в карточке приходит на языке запроса
// (Accept-Language), поэтому язык — часть ключа выдачи. Смена фильтра не стирает экран: прежняя
// выдача видна, пока грузится новая.
import type {
  CategoryCountsOut,
  Locale,
  SearchCountSpecialistsParams,
  SearchListSpecialistsParams,
  SpecialistCardOut,
  SpecialistPageOut,
} from '@sosed/api-client';
import {
  getSearchCountByCategoryQueryKey,
  getSearchCountSpecialistsQueryKey,
  getSearchListSpecialistsQueryKey,
  getSearchSuggestQueryKey,
  searchCountByCategory,
  searchCountSpecialists,
  searchListSpecialists,
  searchSuggest,
} from '@sosed/api-client';
import type { InfiniteData } from '@tanstack/react-query';
import { keepPreviousData, queryOptions, useInfiniteQuery, useQuery } from '@tanstack/react-query';

export const SEARCH_PAGE_SIZE = 20;
/** Как Cache-Control ответа (max-age=300): числа в дереве меняются не чаще публикаций. */
export const CATEGORY_COUNTS_STALE_MS = 5 * 60_000;

/** Запрос выдачи без страницы: текст, фильтры, порядок. */
export type SpecialistQuery = Omit<SearchListSpecialistsParams, 'limit' | 'cursor'>;
export type SpecialistResults = InfiniteData<SpecialistPageOut, string | null>;

function required<T>(value: T | null): T {
  if (value === null) throw new Error('query is disabled without parameters');
  return value;
}

export function specialistsQueryKey(locale: Locale, query: SpecialistQuery) {
  return [...getSearchListSpecialistsQueryKey(query), locale] as const;
}

/** `null` — запрашивать нечего (город ещё не известен). */
export function useSpecialistSearch(locale: Locale, query: SpecialistQuery | null) {
  return useInfiniteQuery({
    queryKey: specialistsQueryKey(locale, query ?? { city_id: 0 }),
    queryFn: ({ pageParam, signal }) =>
      searchListSpecialists(
        pageParam === null
          ? { ...required(query), limit: SEARCH_PAGE_SIZE }
          : { ...required(query), limit: SEARCH_PAGE_SIZE, cursor: pageParam },
        { signal },
      ),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor ?? null,
    enabled: query !== null,
    placeholderData: keepPreviousData,
  });
}

/** Карточки всех загруженных страниц подряд. */
export function resultItems(results: Pick<SpecialistResults, 'pages'> | undefined) {
  return results?.pages.flatMap((page) => page.items) ?? ([] as SpecialistCardOut[]);
}

/** Что сервер понял из запроса — по первой странице: категории, подсказка, советы. */
export function resultSummary(results: Pick<SpecialistResults, 'pages'> | undefined) {
  const first = results?.pages[0];
  return {
    categoryIds: first?.category_ids ?? [],
    didYouMean: first?.did_you_mean ?? null,
    hints: first?.hints ?? [],
  };
}

/** Тот же запрос для «Показать N»: порядок и «срочно» на число не влияют. */
export function countQuery(query: SpecialistQuery): SearchCountSpecialistsParams {
  const filters: SpecialistQuery = { ...query };
  delete filters.sort;
  delete filters.urgent;
  return filters;
}

export function useSpecialistCount(query: SpecialistQuery | null) {
  const params = query === null ? null : countQuery(query);
  return useQuery({
    queryKey: getSearchCountSpecialistsQueryKey(params ?? { city_id: 0 }),
    queryFn: ({ signal }) => searchCountSpecialists(required(params), { signal }),
    enabled: params !== null,
    placeholderData: keepPreviousData,
  });
}

export function countsByCategory(out: CategoryCountsOut): ReadonlyMap<number, number> {
  return new Map(out.items.map((item) => [item.category_id, item.count]));
}

/** Сколько видимых специалистов в каждой категории города (с подкатегориями). */
export function useCategoryCounts(cityId: number | null) {
  return useQuery({
    queryKey: getSearchCountByCategoryQueryKey({ city_id: cityId ?? 0 }),
    queryFn: ({ signal }) => searchCountByCategory({ city_id: required(cityId) }, { signal }),
    enabled: cityId !== null,
    staleTime: CATEGORY_COUNTS_STALE_MS,
    select: countsByCategory,
  });
}

/** Подсказки — с двух букв, как у backend (4.3a). */
export const SUGGEST_MIN = 2;
/** Длиннее backend не принимает (`q` до 64 знаков, иначе 422), а подбирает по первым словам. */
export const SUGGEST_MAX = 64;
/** Как Cache-Control ответа (max-age=300). */
export const SUGGEST_STALE_MS = 5 * 60_000;

/** Запрос подсказок из набранного: пробелы схлопнуты, длинный текст (заголовок заявки S20a — до
 *  120 знаков) — первыми словами в пределах SUGGEST_MAX, без обрезанного слова на конце. */
export function suggestQuery(text: string): string {
  const q = text.split(/\s+/).filter(Boolean).join(' ');
  if (q.length <= SUGGEST_MAX) return q;
  const cut = q.slice(0, SUGGEST_MAX + 1);
  const space = cut.lastIndexOf(' ');
  return (space > 0 ? cut.slice(0, space) : q.slice(0, SUGGEST_MAX)).trim();
}

/** Подсказки при вводе (`GET /suggest`): названия на языке запроса — язык в ключе. Текст
 *  приходит уже с задержкой (экран ждёт, пока человек перестанет печатать). */
export function useSuggest(text: string, locale: Locale) {
  const q = suggestQuery(text);
  return useQuery({
    queryKey: [...getSearchSuggestQueryKey({ q }), locale] as const,
    queryFn: ({ signal }) => searchSuggest({ q }, { signal }),
    enabled: q.length >= SUGGEST_MIN,
    staleTime: SUGGEST_STALE_MS,
    placeholderData: keepPreviousData,
  });
}

/** Карточек «Свободны сегодня рядом» на Главной — как на артборде S03. */
export const TODAY_PREVIEW = 2;

/** Запрос «Свободны сегодня рядом» — один у хука и у предзагрузки Главной после входа. */
export function availableTodayQueryOptions(
  locale: Locale,
  cityId: number | null,
  point: { lat: number; lon: number } | null,
) {
  const query: SpecialistQuery | null =
    cityId === null
      ? null
      : point
        ? { city_id: cityId, available_today: true, sort: 'distance', ...point }
        : { city_id: cityId, available_today: true };
  const params = query === null ? null : { ...query, limit: TODAY_PREVIEW };
  return queryOptions({
    queryKey: [...getSearchListSpecialistsQueryKey(params ?? { city_id: 0 }), locale] as const,
    queryFn: ({ signal }) => searchListSpecialists(required(params), { signal }),
    enabled: params !== null,
  });
}

/** «Свободны сегодня рядом»: доступные сегодня в городе; с точкой клиента — ближние первыми. */
export function useAvailableToday(
  locale: Locale,
  cityId: number | null,
  point: { lat: number; lon: number } | null,
) {
  return useQuery({
    ...availableTodayQueryOptions(locale, cityId, point),
    placeholderData: keepPreviousData,
  });
}
