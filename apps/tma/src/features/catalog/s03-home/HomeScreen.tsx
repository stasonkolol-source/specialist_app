// S03 Главная (DEVELOPMENT_PLAN 4.8): точка входа клиента из блоков каталога — поэтому экран в
// фиче catalog (фичи не импортируют друг друга). Чип города: нажатие спрашивает местоположение у
// Telegram — «Нови-Сад · Лиман», и «Свободны сегодня рядом» — ближние первыми. Строка поиска с
// подсказками `/suggest` (с задержкой): подсказка ведёт в выдачу категории, Enter — в выдачу по
// тексту. Плитки разделов — в выдачу раздела, «Все услуги» — в S04. Переключатель «Услуги / Вещи
// · скоро» — по флагу goods.segment (client-config, ADR-0019; Q26: в бете выключен, включает
// админка без релиза): «Вещи» в MVP — S58 с подпиской на запуск (7.5), своим чанком (GoodsSoon.tsx).
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
  Badge,
  Banner,
  Button,
  Card,
  Chip,
  ChipSkeleton,
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
import { Suspense, lazy, useEffect, useId, useState } from 'react';

import { useCatalogCityState } from '../shared/city.ts';
import { useDebounced } from '../shared/debounce.ts';
import type { ClientPoint } from '../shared/location.ts';
import { useLocate } from '../shared/location.ts';
import type { ResultsSearch } from '../shared/paths.ts';
import { CATALOG_PATHS, CREATE_JOB_PATH, JOBS_FEED_PATH } from '../shared/paths.ts';
import { rememberedRows } from './activeJobs.ts';
import { GoodsIntro } from './GoodsIntro.tsx';

type Segment = 'services' | 'goods';

/** Плиток разделов до «Все услуги» — как на артборде: два ряда по три. */
const TILES = 5;
/** Цвета плиток по порядку разделов — как на артборде. */
const PALETTES: readonly AvatarPalette[] = [1, 4, 2, 3, 5];
/** Подсказки — когда человек перестал печатать. */
const SUGGEST_DELAY_MS = 250;

/** Необязательный блок своим чанком: не скачался (пропала сеть) — блока нет, а Главная работает.
 *  Иначе ошибка чанка дошла бы до экрана ошибки и закрыла бы всю Главную. Чанки блоков качаются
 *  все сразу после первого кадра Главной (useFirstFramePainted), параллельно с данными блоков, а не
 *  после них: lazy отдаёт уже начатую загрузку. До кадра сеть — у шрифтов и данных первого экрана:
 *  полтора десятка мелких чанков на медленном 4G отодвигали его (LCP). */
function optionalChunk<P extends object>(load: () => Promise<ComponentType<P>>) {
  let loading: Promise<{ default: ComponentType<P> }> | null = null;
  const preload = (): Promise<{ default: ComponentType<P> }> =>
    (loading ??= load().then(
      (component) => ({ default: component }),
      () => ({ default: () => null }),
    ));
  return Object.assign(lazy(preload), { preload });
}

/** true — первый кадр экрана нарисован: rAF срабатывает перед кадром, таймер из него — после. */
function useFirstFramePainted(): boolean {
  const [painted, setPainted] = useState(false);
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | undefined;
    const frame = requestAnimationFrame(() => {
      timer = setTimeout(() => setPainted(true), 0);
    });
    return () => {
      cancelAnimationFrame(frame);
      clearTimeout(timer);
    };
  }, []);
  return painted;
}

const TodayNearby = optionalChunk(() =>
  import('./TodayNearby.tsx').then((module) => module.TodayNearby),
);
const SideJob = optionalChunk(() => import('./SideJob.tsx').then((module) => module.SideJob));
const MyActiveJobs = optionalChunk(() =>
  import('./MyActiveJobs.tsx').then((module) => module.MyActiveJobs),
);
// S58 качается, только когда выбрали «Вещи»; не скачался — остаётся шапка «Вещи — скоро»
const GoodsSoon = lazy(() =>
  import('./GoodsSoon.tsx').then(
    (module) => ({ default: module.GoodsSoon }),
    () => ({ default: GoodsIntro }),
  ),
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
            {
              value: 'goods',
              icon: 'bag',
              label: (
                <>
                  {t('home.goods')}
                  <Badge tone="info" className="h-5 px-1.5 text-[11px]">
                    {t('home.soon')}
                  </Badge>
                </>
              ),
            },
          ]}
        />
      )}
      {showGoods ? (
        <Suspense fallback={<GoodsIntro />}>
          <GoodsSoon />
        </Suspense>
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
  const user = useQueryClient().getQueryData<MeOut>(getIdentityGetMeQueryKey())?.id ?? null;
  // свои заявки — над разделами. Место под блок до ответа — только если в прошлый раз они были, и
  // под столько же строк (activeJobs.ts): плитки не прыгают ни вниз, ни вверх
  const reserved = signedIn && user ? rememberedRows(user) : 0;
  const reserve = reserved > 0 ? <MyActiveJobsSkeleton rows={reserved} /> : null;
  const locate = useLocate();
  const [point, setPoint] = useState<ClientPoint | null>(null);
  const [locationFailed, setLocationFailed] = useState(false);
  // районы — только когда есть точка: чипу нужен ближайший
  const districts = useDistricts(point && city ? city.id : null, locale);
  const district = point && districts.data ? nearestDistrict(districts.data, point) : null;
  const today = useAvailableToday(locale, city ? city.id : null, point);
  const cards = today.data?.items ?? [];
  const categoriesId = useId();
  // необязательные блоки — после первого кадра (optionalChunk); их данные запрошены раньше (warm.ts)
  const painted = useFirstFramePainted();
  useEffect(() => {
    if (!painted) return;
    void TodayNearby.preload();
    void SideJob.preload();
    if (signedIn) void MyActiveJobs.preload();
  }, [painted, signedIn]);

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
      {signedIn &&
        (painted ? (
          <Suspense fallback={reserve}>
            <MyActiveJobs user={user} pending={reserve} />
          </Suspense>
        ) : (
          reserve
        ))}
      <section aria-labelledby={categoriesId} className="flex flex-col gap-3">
        <Heading variant="h3" as="h2" id={categoriesId}>
          {t('home.whatToDo')}
        </Heading>
        <Sections onOpen={(id) => results({ category: id })} href={href} />
      </section>
      <CreateJob onOpen={() => void router.navigate({ to: CREATE_JOB_PATH })} />
      {painted && cards.length > 0 && (
        <Suspense fallback={null}>
          <TodayNearby
            cards={cards}
            allHref={href(CATALOG_PATHS.results, { today: true, ...near })}
            onAll={results({ today: true, ...near })}
          />
        </Suspense>
      )}
      {painted && city && (
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

/** «Мои активные заявки», пока список не пришёл: заголовок и строки — сколько было в прошлый раз. */
function MyActiveJobsSkeleton({ rows }: { rows: number }) {
  return (
    <div aria-hidden="true" className="flex flex-col gap-3">
      <SkeletonText size="h3" screen className="w-2/5" />
      <RowsSkeleton rows={rows} leading="icon" />
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
