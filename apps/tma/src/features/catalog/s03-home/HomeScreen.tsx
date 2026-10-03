// S03 Главная (DEVELOPMENT_PLAN 4.8): точка входа клиента из блоков каталога — поэтому экран в
// фиче catalog (фичи не импортируют друг друга). Чип города: нажатие спрашивает местоположение у
// Telegram — «Нови-Сад · Лиман», и «Свободны сегодня рядом» — ближние первыми. Строка поиска с
// подсказками `/suggest` (с задержкой): подсказка ведёт в выдачу категории, Enter — в выдачу по
// тексту. Плитки разделов — в выдачу раздела, «Все услуги» — в S04. Переключатель «Услуги / Вещи»
// — по флагу goods.segment (client-config, ADR-0019): «Вещи» в MVP — заглушка S58.
// «Не хотите искать сами?» ведёт в мастер заявки S20a (5.2), «Ищете подработку?» — в ленту заявок
// S13 (5.3): число заявок за сутки, без новых блока нет. «Мои активные заявки» (5.6) — у клиента с
// открытыми заявками, сразу под поиском. «Свободны сегодня рядом», «Ищете подработку?» и «Мои
// активные заявки» — своими чанками (TodayNearby.tsx, SideJob.tsx, MyActiveJobs.tsx): до первого
// кадра Главной они не нужны.
import type { CategoryOut, MeOut, SuggestionOut } from '@sosed/api-client';
import { getIdentityGetMeQueryKey, getSession } from '@sosed/api-client';
import {
  FLAGS,
  nearestDistrict,
  useAvailableToday,
  useCategories,
  useDistricts,
  useFlag,
  useSuggest,
} from '@sosed/hooks';
import { useLocale, useTranslation } from '@sosed/i18n';
import type { AvatarPalette, IconName } from '@sosed/ui-web';
import {
  Banner,
  Button,
  Card,
  Chip,
  ChipSkeleton,
  EmptyState,
  Group,
  Heading,
  ICON_NAMES,
  Row,
  RowIcon,
  RowsSkeleton,
  SearchField,
  Segmented,
  SkeletonText,
  Text,
  Tile,
  TileSkeleton,
  Tiles,
} from '@sosed/ui-web';
import { useQueryClient } from '@tanstack/react-query';
import { useRouter } from '@tanstack/react-router';
import type { ComponentType, FormEvent, MouseEvent } from 'react';
import { Suspense, lazy, useId, useState } from 'react';

import { useCatalogCityState } from '../shared/city.ts';
import { useDebounced } from '../shared/debounce.ts';
import type { ClientPoint } from '../shared/location.ts';
import { useLocate } from '../shared/location.ts';
import type { ResultsSearch } from '../shared/paths.ts';
import { CATALOG_PATHS, CREATE_JOB_PATH, JOBS_FEED_PATH } from '../shared/paths.ts';

type Segment = 'services' | 'goods';

/** Плиток разделов до «Все услуги» — как на артборде: два ряда по три. */
const TILES = 5;
/** Цвета плиток по порядку разделов — как на артборде. */
const PALETTES: readonly AvatarPalette[] = [1, 4, 2, 3, 5];
/** Подсказки — когда человек перестал печатать. */
const SUGGEST_DELAY_MS = 250;

/** Необязательный блок своим чанком: не скачался (пропала сеть) — блока нет, а Главная работает.
 *  Иначе ошибка чанка дошла бы до экрана ошибки и закрыла бы всю Главную. Чанк качается сразу с
 *  Главной, параллельно с данными блока, а не после них: lazy отдаёт уже начатую загрузку. */
function optionalChunk<P extends object>(load: () => Promise<ComponentType<P>>) {
  const loading: Promise<{ default: ComponentType<P> }> = load().then(
    (component) => ({ default: component }),
    () => ({ default: () => null }),
  );
  return lazy(() => loading);
}

const TodayNearby = optionalChunk(() =>
  import('./TodayNearby.tsx').then((module) => module.TodayNearby),
);
const SideJob = optionalChunk(() => import('./SideJob.tsx').then((module) => module.SideJob));
const MyActiveJobs = optionalChunk(() =>
  import('./MyActiveJobs.tsx').then((module) => module.MyActiveJobs),
);

const iconOf = (name: string | null): IconName =>
  (ICON_NAMES as readonly string[]).includes(name ?? '') ? (name as IconName) : 'grid';

export function HomeScreen() {
  const { t } = useTranslation();
  const goodsSegment = useFlag(FLAGS.goodsSegment);
  const [segment, setSegment] = useState<Segment>('services');
  const showGoods = goodsSegment && segment === 'goods';
  return (
    <section className="flex flex-col gap-5 px-4 pt-3 pb-6">
      {goodsSegment && (
        <Segmented<Segment>
          label={t('home.segment')}
          value={segment}
          onChange={setSegment}
          options={[
            { value: 'services', label: t('home.services') },
            { value: 'goods', label: t('home.goods') },
          ]}
        />
      )}
      {showGoods ? (
        <EmptyState as="h1" icon="bag" title={t('goods.soonTitle')}>
          {t('goods.soonText')}
        </EmptyState>
      ) : (
        <Services />
      )}
    </section>
  );
}

function Services() {
  // гостю своих заявок нет: без сессии список не запрашивается
  const signedIn = getSession() !== null;
  const { t } = useTranslation('catalog');
  const locale = useLocale();
  const router = useRouter();
  const { city, pending: cityPending } = useCatalogCityState();
  // клиент с заявками видит их над разделами: место под блок — до ответа, плитки не прыгают вниз
  const client =
    useQueryClient().getQueryData<MeOut>(getIdentityGetMeQueryKey())?.intent === 'client';
  const locate = useLocate();
  const [point, setPoint] = useState<ClientPoint | null>(null);
  const [locationFailed, setLocationFailed] = useState(false);
  // районы — только когда есть точка: чипу нужен ближайший
  const districts = useDistricts(point && city ? city.id : null, locale);
  const district = point && districts.data ? nearestDistrict(districts.data, point) : null;
  const today = useAvailableToday(locale, city ? city.id : null, point);
  const cards = today.data?.items ?? [];
  const categoriesId = useId();

  const results = (search: ResultsSearch) => (event?: MouseEvent<HTMLElement>) => {
    event?.preventDefault();
    void router.navigate({ to: CATALOG_PATHS.results, search });
  };
  const href = (to: string, search?: ResultsSearch) =>
    router.history.createHref(router.buildLocation({ to, search }).href);
  const near: ResultsSearch = point ? { sort: 'distance', ...point } : {};
  const askLocation = async () => {
    setLocationFailed(false);
    const found = await locate();
    if (found) setPoint(found);
    else setLocationFailed(true);
  };

  return (
    <>
      <section className="flex flex-col gap-3">
        {city ? (
          <span className="self-start">
            <Chip icon="pin" onClick={() => void askLocation()}>
              {district ? `${city.name} · ${district.name}` : city.name}
            </Chip>
          </span>
        ) : (
          cityPending && <ChipSkeleton className="w-32 self-start" />
        )}
        <div className="flex flex-col gap-1">
          <Heading variant="h1">{t('home.title')}</Heading>
          <Text secondary>{t('home.subtitle')}</Text>
        </div>
        <Search onCategory={(id) => results({ category: id })()} />
        {locationFailed && (
          <Banner tone="warn" role="alert">
            {t('results.locationError')}
          </Banner>
        )}
      </section>
      {signedIn && (
        <Suspense fallback={client ? <MyActiveJobsSkeleton /> : null}>
          <MyActiveJobs pending={client ? <MyActiveJobsSkeleton /> : null} />
        </Suspense>
      )}
      <section aria-labelledby={categoriesId} className="flex flex-col gap-3">
        <Heading variant="h3" as="h2" id={categoriesId}>
          {t('home.whatToDo')}
        </Heading>
        <Sections onOpen={(id) => results({ category: id })} href={href} />
      </section>
      <CreateJob onOpen={() => void router.navigate({ to: CREATE_JOB_PATH })} />
      {cards.length > 0 && (
        <Suspense fallback={null}>
          <TodayNearby
            cards={cards}
            allHref={href(CATALOG_PATHS.results, { today: true, ...near })}
            onAll={results({ today: true, ...near })}
          />
        </Suspense>
      )}
      {city && (
        <Suspense fallback={null}>
          <SideJob
            cityId={city.id}
            href={href(JOBS_FEED_PATH)}
            onOpen={(event) => {
              event.preventDefault();
              void router.navigate({ to: JOBS_FEED_PATH });
            }}
          />
        </Suspense>
      )}
    </>
  );
}

/** «Мои активные заявки», пока список не пришёл: заголовок и строка. */
function MyActiveJobsSkeleton() {
  return (
    <div aria-hidden="true" className="flex flex-col gap-3">
      <SkeletonText size="h3" screen className="w-2/5" />
      <RowsSkeleton rows={1} leading="icon" />
    </div>
  );
}

/** «Не хотите искать сами?»: описать задачу — откликнутся до пяти исполнителей. */
function CreateJob({ onOpen }: { onOpen: () => void }) {
  const { t } = useTranslation('catalog');
  return (
    <Card className="flex flex-col gap-3">
      <div className="flex items-start gap-3">
        <RowIcon icon="jobs" xl />
        <div className="flex min-w-0 flex-col gap-1">
          <Heading variant="h3" as="h2">
            {t('home.createTitle')}
          </Heading>
          <Text variant="sm" secondary>
            {t('home.createText')}
          </Text>
        </div>
      </div>
      <Button full onClick={onOpen}>
        {t('home.create')}
      </Button>
    </Card>
  );
}

/** Строка поиска: Enter — выдача по тексту, подсказка — выдача её категории. */
function Search({ onCategory }: { onCategory: (categoryId: number) => void }) {
  const { t } = useTranslation('catalog');
  const locale = useLocale();
  const router = useRouter();
  const [typed, setTyped] = useState('');
  const settled = useDebounced(typed, SUGGEST_DELAY_MS);
  const suggest = useSuggest(settled, locale);
  const suggestions = typed.trim() ? (suggest.data?.items ?? []) : [];
  const submit = (event: FormEvent) => {
    event.preventDefault();
    const q = typed.trim();
    if (q) void router.navigate({ to: CATALOG_PATHS.results, search: { q } });
  };
  return (
    <div className="flex flex-col gap-2">
      <form onSubmit={submit}>
        <SearchField
          label={t('results.search')}
          placeholder={t('home.search')}
          value={typed}
          onChange={(event) => setTyped(event.target.value)}
        />
      </form>
      {suggestions.length > 0 && (
        <nav aria-label={t('home.suggestions')}>
          <Group>
            {suggestions.map((item) => (
              <Suggestion key={item.category_id} item={item} onOpen={onCategory} />
            ))}
          </Group>
        </nav>
      )}
    </div>
  );
}

function Suggestion({
  item,
  onOpen,
}: {
  item: SuggestionOut;
  onOpen: (categoryId: number) => void;
}) {
  // слово словаря, которым узнан ввод, — подписью, если оно не название категории
  const term = item.term.toLowerCase() === item.name.toLowerCase() ? undefined : item.term;
  return (
    <Row
      leading={<RowIcon icon={iconOf(item.icon)} />}
      title={item.name}
      subtitle={term}
      onClick={() => onOpen(item.category_id)}
    />
  );
}

/** Разделы каталога плитками и «Все услуги». */
function Sections({
  onOpen,
  href,
}: {
  onOpen: (categoryId: number) => (event?: MouseEvent<HTMLElement>) => void;
  href: (to: string, search?: ResultsSearch) => string;
}) {
  const { t } = useTranslation('catalog');
  const router = useRouter();
  const query = useCategories(useLocale());
  const categories: CategoryOut[] = query.data ?? [];
  return (
    <Tiles>
      {/* пока разделов нет — плитки той же сетки, что на S01: «Все услуги» не остаётся одна */}
      {query.isPending && Array.from({ length: TILES }, (_, index) => <TileSkeleton key={index} />)}
      {categories.slice(0, TILES).map((section, index) => (
        <Tile
          key={section.id}
          label={section.name}
          icon={iconOf(section.icon)}
          palette={PALETTES[index % PALETTES.length]}
          href={href(CATALOG_PATHS.results, { category: section.id })}
          onClick={onOpen(section.id)}
        />
      ))}
      <Tile
        label={t('categories.title')}
        icon="grid"
        neutral
        href={href(CATALOG_PATHS.categories)}
        onClick={(event) => {
          event.preventDefault();
          void router.navigate({ to: CATALOG_PATHS.categories });
        }}
      />
    </Tiles>
  );
}
