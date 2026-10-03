// S05 Результаты поиска (DEVELOPMENT_PLAN 4.4): строка поиска, чипы фильтров, сколько нашлось и
// карточки специалистов по страницам. Текст, фильтры и порядок — в адресе: переживают «Назад».
// Опечатку сервер поправил — «Возможно, вы имели в виду …». Пусто — совет ослабить фильтры
// (CTA «Разместите заявку» — с шагом 5.2). «До 3 км» спрашивает местоположение.
// Карточка ведёт в профиль S08 (4.5), сердечко — в избранное (4.6). Гость видит экран без входа,
// но без сердечек.
import {
  resultItems,
  resultSummary,
  useCategories,
  useSpecialistCount,
  useSpecialistSearch,
} from '@sosed/hooks';
import { useLocale, useTranslation } from '@sosed/i18n';
import { useBackButton } from '@sosed/platform';
import {
  Banner,
  Button,
  Chip,
  ChipSkeleton,
  Chips,
  EmptyState,
  IconButton,
  SearchField,
  SkeletonText,
  SpecialistCardSkeleton,
} from '@sosed/ui-web';
import { useRouter, useSearch } from '@tanstack/react-router';
import type { FormEvent } from 'react';
import { useState } from 'react';

import { FiltersSheet } from '../s06-filters/index.ts';
import { LoadError } from '../shared/LoadError.tsx';
import { ResultCard } from '../shared/ResultCard.tsx';
import { useCatalogCity } from '../shared/city.ts';
import { useFavoriteToggle } from '../shared/favorite.ts';
import { useLocate } from '../shared/location.ts';
import type { ResultsSearch } from '../shared/paths.ts';
import { CATALOG_PATHS, CREATE_JOB_PATH, NEAR_KM } from '../shared/paths.ts';
import { activeFilters, toQuery, withoutFilters } from '../shared/query.ts';

const SKELETON_CARDS = 3;

export function ResultsScreen() {
  const { t } = useTranslation('catalog');
  const locale = useLocale();
  const router = useRouter();
  const search: ResultsSearch = useSearch({ strict: false });
  const city = useCatalogCity();
  const query = city ? toQuery(search, city.id) : null;
  const results = useSpecialistSearch(locale, query);
  const count = useSpecialistCount(query);
  const categoryTree = useCategories(locale);
  const categories = categoryTree.data ?? [];
  const locate = useLocate();
  const { control, failure } = useFavoriteToggle();
  const [typed, setTyped] = useState(search.q ?? '');
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [locationFailed, setLocationFailed] = useState(false);
  useBackButton(() => {
    if (router.history.canGoBack()) router.history.back();
    else void router.navigate({ to: CATALOG_PATHS.categories, replace: true });
  });

  // фильтры меняют адрес без новой записи в истории: «Назад» уводит с выдачи, а не по фильтрам
  const update = (next: ResultsSearch) =>
    void router.navigate({ to: CATALOG_PATHS.results, search: next, replace: true });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    update({ ...search, q: typed.trim() || undefined });
  };
  const toggleNear = async () => {
    setLocationFailed(false);
    if (search.near !== undefined) {
      update({ ...search, near: undefined });
      return;
    }
    const point =
      search.lat !== undefined && search.lon !== undefined
        ? { lat: search.lat, lon: search.lon }
        : await locate();
    if (point) update({ ...search, ...point, near: NEAR_KM });
    else setLocationFailed(true);
  };

  const items = resultItems(results.data);
  const summary = resultSummary(results.data);
  const filters = activeFilters(search);
  const category =
    search.category === undefined
      ? undefined
      : categories
          .flatMap((node) => [node, ...node.children])
          .find((node) => node.id === search.category);
  const near = search.lat !== undefined && search.lon !== undefined;

  let content;
  if (results.data) {
    content =
      items.length === 0 ? (
        <EmptyState
          icon="search"
          as="h2"
          title={t('results.emptyTitle')}
          action={
            filters > 0 ? (
              <Button variant="secondary" onClick={() => update(withoutFilters(search))}>
                {t('results.resetFilters')}
              </Button>
            ) : (
              <Button
                variant="secondary"
                onClick={() =>
                  void router.navigate({
                    to: CREATE_JOB_PATH,
                    search: { category: search.category, title: search.q },
                  })
                }
              >
                {t('results.postJob')}
              </Button>
            )
          }
        >
          {filters > 0 ? t('results.relaxFilters') : t('results.postJobText')}
        </EmptyState>
      ) : (
        <>
          {summary.didYouMean && (
            <Banner tone="info">{t('results.didYouMean', { term: summary.didYouMean })}</Banner>
          )}
          <div className="flex flex-col gap-2.5">
            {items.map((item) => (
              <ResultCard key={item.profile_id} card={item} favorite={control(item)} />
            ))}
          </div>
          {results.hasNextPage && (
            <Button
              variant="secondary"
              full
              onClick={() => void results.fetchNextPage()}
              disabled={results.isFetchingNextPage}
              aria-busy={results.isFetchingNextPage}
            >
              {t('results.more')}
            </Button>
          )}
          {results.isFetchNextPageError && (
            <Banner tone="danger" role="alert">
              {t('results.moreError')}
            </Banner>
          )}
        </>
      );
  } else if (results.isError) {
    content = (
      <LoadError
        error={results.error}
        onRetry={() => void results.refetch()}
        retrying={results.isRefetching}
      />
    );
  } else {
    content = (
      <div className="flex flex-col gap-2.5" aria-busy="true">
        {Array.from({ length: SKELETON_CARDS }, (_, card) => (
          <SpecialistCardSkeleton key={card} />
        ))}
      </div>
    );
  }

  return (
    <section className="flex flex-col gap-3 px-4 pt-3 pb-6">
      {/* на макете заголовка нет: строка поиска и есть «шапка»; скринридеру — h1 экрана */}
      <h1 className="sr-only">{t('results.title')}</h1>
      <form onSubmit={submit}>
        <SearchField
          label={t('results.search')}
          placeholder={t('results.search')}
          value={typed}
          onChange={(event) => setTyped(event.target.value)}
          trailing={
            typed ? (
              <IconButton
                plain
                icon="x"
                label={t('results.clear')}
                className="-mr-3"
                onClick={() => {
                  setTyped('');
                  update({ ...search, q: undefined });
                }}
              />
            ) : undefined
          }
        />
      </form>
      <Chips label={t('results.chips')} className="-mx-4 overflow-x-auto px-4">
        <Chip icon="sliders" count={filters || undefined} onClick={() => setFiltersOpen(true)}>
          {t('results.filters')}
        </Chip>
        {category ? (
          <Chip selected onClick={() => update({ ...search, category: undefined })}>
            {category.name}
          </Chip>
        ) : (
          search.category !== undefined &&
          categoryTree.isPending && <ChipSkeleton className="w-28" />
        )}
        <Chip
          selected={search.today === true}
          onClick={() => update({ ...search, today: search.today ? undefined : true })}
        >
          {t('filters.availableToday')}
        </Chip>
        <Chip selected={search.near !== undefined} onClick={() => void toggleNear()}>
          {t('filters.nearMe', { km: NEAR_KM })}
        </Chip>
      </Chips>
      {failure && (
        <Banner tone="danger" role="alert">
          {failure}
        </Banner>
      )}
      {locationFailed && (
        <Banner tone="warn" role="alert">
          {t('results.locationError')}
        </Banner>
      )}
      {/* строка «Нашли N» — над выдачей: место под неё держим, пока число не пришло */}
      {!count.data && count.isPending && <SkeletonText size="cap" screen className="w-40" />}
      {count.data && count.data.count > 0 && (
        <p className="m-0 text-cap text-text2" aria-live="polite">
          {count.data.capped
            ? t('results.countMore', { count: count.data.count })
            : near
              ? t('results.countNear', { count: count.data.count })
              : t('results.count', { count: count.data.count })}
        </p>
      )}
      {content}
      {filtersOpen && (
        <FiltersSheet
          search={search}
          city={city}
          onClose={() => setFiltersOpen(false)}
          onApply={(next) => {
            setFiltersOpen(false);
            update(next);
          }}
        />
      )}
    </section>
  );
}
