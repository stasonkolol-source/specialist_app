// Справочники мастера S32b–c: категории (GET /categories) и районы города (GET
// /cities/{id}/districts). Названия приходят на языке запроса (Accept-Language), поэтому язык —
// часть ключа: после смены языка без перезагрузки список перечитывается, а до ответа виден прежний.
import type { CategoryOut, DistrictOut, Locale } from '@sosed/api-client';
import {
  getCatalogListCategoriesQueryKey,
  getGeoListDistrictsQueryKey,
  useCatalogListCategories,
  useGeoListDistricts,
} from '@sosed/api-client';
import { keepPreviousData } from '@tanstack/react-query';

/** Как Cache-Control ответов (max-age=300): справочники меняются редко. */
export const DICTIONARY_STALE_MS = 5 * 60_000;

export function categoriesQueryKey(locale: Locale) {
  return [...getCatalogListCategoriesQueryKey(), locale] as const;
}

export function useCategories(locale: Locale) {
  return useCatalogListCategories(undefined, {
    query: {
      queryKey: categoriesQueryKey(locale),
      staleTime: DICTIONARY_STALE_MS,
      placeholderData: keepPreviousData,
    },
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
