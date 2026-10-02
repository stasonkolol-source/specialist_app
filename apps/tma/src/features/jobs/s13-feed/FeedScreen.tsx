// S13 Лента заявок (DEVELOPMENT_PLAN 5.3): сегмент «Лента» вкладки «Заявки» — заявки города,
// новые сверху. Чипы: «Фильтры N» открывает шторку S14, «До 3 км» спрашивает местоположение,
// выбранные категории снимаются нажатием, «Сегодня» и «Срочные» — быстрые фильтры. Фильтры — в
// адресе: переживают «Назад» из заявки. Список виртуальный (FeedList.tsx); следующая страница
// грузится, когда кнопка «Показать ещё» доезжает до экрана. Скрыто до своих шагов: колокольчик
// подписок S18 и «По моим подпискам» (5.7).
// Гость видит ленту без входа.
import type { CategoryOut } from '@sosed/api-client';
import {
  jobCards,
  selectableDistricts,
  useCategories,
  useDistricts,
  useJobsCount,
  useJobsFeed,
} from '@sosed/hooks';
import { useLocale, useTranslation } from '@sosed/i18n';
import { Banner, Button, Chip, Chips, EmptyState, Heading, Skeleton } from '@sosed/ui-web';
import { useRouter, useSearch } from '@tanstack/react-router';
import { useEffect, useEffectEvent, useRef, useState } from 'react';

import { FiltersSheet } from '../s14-feed-filters/index.ts';
import { FeedCard } from '../shared/FeedCard.tsx';
import { JobsSegments } from '../shared/JobsSegments.tsx';
import { LoadError } from '../shared/LoadError.tsx';
import { findCategory } from '../shared/categories.ts';
import { useFeedCity } from '../shared/city.ts';
import type { FeedSearch } from '../shared/feed.ts';
import { NEAR_KM, activeFilters, toFeedQuery, toggle, withoutFilters } from '../shared/feed.ts';
import { useLocate } from '../shared/location.ts';
import { JOBS_PATHS } from '../shared/paths.ts';
import { FeedList } from './FeedList.tsx';

const SKELETON_CARDS = 3;

export function FeedScreen() {
  const { t } = useTranslation('jobs');
  const locale = useLocale();
  const router = useRouter();
  const search: FeedSearch = useSearch({ strict: false });
  const city = useFeedCity();
  const query = city ? toFeedQuery(search, city.id) : null;
  const feed = useJobsFeed(query);
  const count = useJobsCount(query);
  const tree = useCategories(locale).data ?? [];
  const districts = selectableDistricts(useDistricts(city?.id ?? null, locale).data ?? [], locale);
  const locate = useLocate();
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [locationFailed, setLocationFailed] = useState(false);

  // фильтры меняют адрес без новой записи в истории: «Назад» уводит с ленты, а не по фильтрам
  const update = (next: FeedSearch) =>
    void router.navigate({ to: JOBS_PATHS.feed, search: next, replace: true });
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

  const cards = jobCards(feed.data);
  const filters = activeFilters(search);
  const point = search.lat !== undefined && search.lon !== undefined;
  const pointSearch = point ? { lat: search.lat, lon: search.lon } : {};
  const districtName = (id: number | null) =>
    id === null ? null : (districts.find((district) => district.id === id)?.name ?? null);
  const categoryName = (id: number) => findCategory(tree, id)?.name ?? null;

  let content;
  if (feed.data) {
    content =
      cards.length === 0 ? (
        <EmptyState
          as="h2"
          icon={filters > 0 ? 'search' : 'jobs'}
          title={filters > 0 ? t('feed.emptyFilteredTitle') : t('feed.emptyTitle')}
          action={
            filters > 0 ? (
              <Button variant="secondary" onClick={() => update(withoutFilters(search))}>
                {t('feed.resetFilters')}
              </Button>
            ) : undefined
          }
        >
          {filters > 0 ? t('feed.emptyFilteredText') : t('feed.emptyText')}
        </EmptyState>
      ) : (
        <>
          <FeedList
            cards={cards}
            render={(card) => (
              <FeedCard
                card={card}
                category={categoryName(card.category_id)}
                district={districtName(card.district_id)}
                point={pointSearch}
              />
            )}
          />
          {feed.hasNextPage && (
            <MoreButton
              loading={feed.isFetchingNextPage}
              failed={feed.isFetchNextPageError}
              onMore={() => void feed.fetchNextPage()}
            />
          )}
          {feed.isFetchNextPageError && (
            <Banner tone="danger" role="alert">
              {t('feed.moreError')}
            </Banner>
          )}
        </>
      );
  } else if (feed.isError) {
    content = (
      <LoadError
        error={feed.error}
        onRetry={() => void feed.refetch()}
        retrying={feed.isRefetching}
      />
    );
  } else {
    content = (
      <div className="flex flex-col gap-2.5" aria-busy="true">
        {Array.from({ length: SKELETON_CARDS }, (_, card) => (
          <Skeleton key={card} radius="card" className="h-36 w-full" />
        ))}
      </div>
    );
  }

  return (
    <section className="flex flex-col gap-3 px-4 pt-3 pb-6">
      <JobsSegments current="feed" />
      <Heading variant="h1">{t('feed.title')}</Heading>
      <Chips label={t('feed.chips')} className="-mx-4 overflow-x-auto px-4">
        <Chip icon="sliders" count={filters || undefined} onClick={() => setFiltersOpen(true)}>
          {t('feed.filters')}
        </Chip>
        <Chip selected={search.near !== undefined} onClick={() => void toggleNear()}>
          {t('feed.near', { km: search.near ?? NEAR_KM })}
        </Chip>
        {search.categories?.map((id) => (
          <CategoryChip
            key={id}
            id={id}
            tree={tree}
            onRemove={() => update({ ...search, categories: toggle(search.categories, id) })}
          />
        ))}
        <Chip
          selected={search.when === 'today'}
          onClick={() => update({ ...search, when: search.when === 'today' ? undefined : 'today' })}
        >
          {t('feed.today')}
        </Chip>
        <Chip
          selected={search.urgent === true}
          onClick={() => update({ ...search, urgent: search.urgent ? undefined : true })}
        >
          {t('feed.urgent')}
        </Chip>
      </Chips>
      {locationFailed && (
        <Banner tone="warn" role="alert">
          {t('feed.locationError')}
        </Banner>
      )}
      {count.data && count.data.count > 0 && (
        <p className="m-0 text-cap text-text2" aria-live="polite">
          {filters > 0
            ? t('feed.countFiltered', { count: count.data.count })
            : t('feed.count', { count: count.data.count })}
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

function CategoryChip({
  id,
  tree,
  onRemove,
}: {
  id: number;
  tree: readonly CategoryOut[];
  onRemove: () => void;
}) {
  const name = findCategory(tree, id)?.name;
  if (!name) return null;
  return (
    <Chip selected onClick={onRemove}>
      {name}
    </Chip>
  );
}

/** «Показать ещё»: сама нажимается, когда доезжает до экрана; руками — если наблюдателя нет. */
function MoreButton({
  loading,
  failed,
  onMore,
}: {
  loading: boolean;
  failed: boolean;
  onMore: () => void;
}) {
  const { t } = useTranslation('jobs');
  const ref = useRef<HTMLDivElement>(null);
  const more = useEffectEvent(onMore);
  // после ошибки — только руками: иначе кнопка в кадре повторяла бы запрос без конца
  const auto = !loading && !failed;
  useEffect(() => {
    const target = ref.current;
    if (!auto || !target || typeof IntersectionObserver === 'undefined') return undefined;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) more();
      },
      { rootMargin: '400px 0px' },
    );
    observer.observe(target);
    return () => observer.disconnect();
  }, [auto]);
  return (
    <div ref={ref}>
      <Button variant="secondary" full onClick={onMore} disabled={loading} aria-busy={loading}>
        {t('feed.more')}
      </Button>
    </div>
  );
}
