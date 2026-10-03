// Справочники мастера S32b–c: категории (GET /categories) и районы города (GET
// /cities/{id}/districts). Названия приходят на языке запроса (Accept-Language), поэтому язык —
// часть ключа: после смены языка без перезагрузки список перечитывается, а до ответа виден прежний.
import type { CategoryOut, DistrictOut, Locale } from '@sosed/api-client';
import {
  getCatalogListCategoriesQueryKey,
  getCatalogListCategoriesQueryOptions,
  getGeoListDistrictsQueryKey,
  useGeoListDistricts,
} from '@sosed/api-client';
import { keepPreviousData, useQuery, useQueryClient } from '@tanstack/react-query';

/** Справочники меняются редко: час без перечитывания (ответ сервера кэшируется на 5 минут —
 *  Cache-Control max-age=300 — и после часа браузер спросит его заново). */
export const DICTIONARY_STALE_MS = 60 * 60_000;

export function categoriesQueryKey(locale: Locale, city?: string) {
  return [...getCatalogListCategoriesQueryKey(city ? { city } : undefined), locale] as const;
}

/** Ключ и свежесть — одни у хука и у предзагрузки при запуске: запрос не задвоится. */
export function categoriesQueryOptions(locale: Locale, city?: string) {
  return getCatalogListCategoriesQueryOptions(city ? { city } : undefined, {
    query: { queryKey: categoriesQueryKey(locale, city), staleTime: DICTIONARY_STALE_MS },
  });
}

/** `city` — slug города: с ним у категорий ориентир цены `price_hint` (S04, S20c); дерево то же.
 *  Пока ориентиров нет — дерево без города из кэша (его грузят Главная и выдача): разделы видны
 *  сразу, а цены дописываются, когда придут. Без города — только для названий, второй запрос не
 *  нужен. */
export function useCategories(locale: Locale, city?: string) {
  const client = useQueryClient();
  return useQuery({
    ...categoriesQueryOptions(locale, city),
    placeholderData: (previous: CategoryOut[] | undefined) =>
      previous ??
      (city ? client.getQueryData<CategoryOut[]>(categoriesQueryKey(locale)) : undefined),
  });
}

/** Листья дерева в порядке каталога: специалист выбирает конкретные услуги, а не разделы. */
export function leafCategories(tree: readonly CategoryOut[]): CategoryOut[] {
  return tree.flatMap((node) =>
    node.children.length > 0 ? leafCategories(node.children) : [node],
  );
}

export function districtsQueryKey(cityId: number, locale: Locale) {
  return [...getGeoListDistrictsQueryKey(cityId), locale] as const;
}

export function useDistricts(cityId: number | null, locale: Locale) {
  return useGeoListDistricts(cityId ?? 0, {
    query: {
      queryKey: districtsQueryKey(cityId ?? 0, locale),
      enabled: cityId !== null,
      staleTime: DICTIONARY_STALE_MS,
      placeholderData: keepPreviousData,
    },
  });
}

/**
 * Районы для выбора: кварталы, без муниципалитета-«всего города», по алфавиту языка интерфейса
 * (сервер отдаёт их по латинскому slug).
 */
export function selectableDistricts(
  districts: readonly DistrictOut[],
  locale: Locale,
): DistrictOut[] {
  return districts
    .filter((district) => district.kind === 'neighborhood')
    .sort((a, b) => a.name.localeCompare(b.name, locale));
}
