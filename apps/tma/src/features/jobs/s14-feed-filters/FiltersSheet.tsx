// S14 Фильтры ленты (DEVELOPMENT_PLAN 5.3): шторка поверх S13. Изменения — черновик: «Показать N»
// (MainButton) применяет их к адресу ленты, «Назад» и крестик закрывают шторку без изменений. N
// считает сервер теми же фильтрами, что и ленту; пока человек нажимает чипы, счёт ждёт (лимит
// гостя — 60 запросов в минуту). Радиус спрашивает местоположение и подписан ближайшим районом:
// «Радиус от Лимана». «Бюджет от» и «Язык общения» выбираются вторым видом шторки. Скрыто до
// своего шага: «Сохранить как подписку» (SecondaryButton, 5.7).
import type { CategoryOut, CityOut } from '@sosed/api-client';
import { color } from '@sosed/design-tokens';
import { rsdToPara } from '@sosed/domain';
import { nearestDistrict, useCategories, useDistricts, useJobsCount } from '@sosed/hooks';
import { useFormat, useLocale, useTranslation } from '@sosed/i18n';
import {
  useBackButton,
  useBottomButtonState,
  useColorScheme,
  useMainButton,
} from '@sosed/platform';
import { Banner, Chip, Chips, Group, Icon, LinkButton, Row, Segmented, Sheet } from '@sosed/ui-web';
import type { ReactNode } from 'react';
import { useId, useMemo, useState } from 'react';

import { findCategory } from '../shared/categories.ts';
import { useDebounced } from '../shared/debounce.ts';
import type { FeedSearch, FeedWhen } from '../shared/feed.ts';
import {
  BUDGET_STEPS,
  FEED_LANGUAGES,
  RADII,
  toFeedQuery,
  toggle,
  withoutFilters,
} from '../shared/feed.ts';
import { useLocate } from '../shared/location.ts';

const COUNT_DELAY_MS = 400;
/** Место под кнопку «Показать N» в браузере: AppShell рисует её поверх шторки. */
const BUTTON_SPACE = 'h-19';

type View = 'filters' | 'budget' | 'language';

export interface FiltersSheetProps {
  search: FeedSearch;
  city: CityOut | null;
  onClose: () => void;
  onApply: (search: FeedSearch) => void;
}

export function FiltersSheet({ search, city, onClose, onApply }: FiltersSheetProps) {
  const { t } = useTranslation('jobs');
  const format = useFormat();
  const [draft, setDraft] = useState<FeedSearch>(search);
  const [view, setView] = useState<View>('filters');
  const [locationFailed, setLocationFailed] = useState(false);
  const locate = useLocate();
  const scheme = useColorScheme();
  const palette = color[scheme];
  const button = useBottomButtonState('main');

  const query = useMemo(() => (city ? toFeedQuery(draft, city.id) : null), [draft, city]);
  const count = useJobsCount(useDebounced(query, COUNT_DELAY_MS));
  const found = count.data;
  const text = !found
    ? t('filters.title')
    : found.count === 0
      ? t('filters.nothing')
      : t('filters.show', { count: found.count });
  useMainButton({
    text,
    onClick: () => onApply(draft),
    visible: view === 'filters',
    enabled: found?.count !== 0,
    color: palette.accent,
    textColor: palette['accent-ink'],
  });
  useBackButton(() => (view === 'filters' ? onClose() : setView('filters')));

  const set = (patch: Partial<FeedSearch>) => setDraft((current) => ({ ...current, ...patch }));
  const pickRadius = async (km: number) => {
    setLocationFailed(false);
    if (draft.near === km) {
      set({ near: undefined });
      return;
    }
    if (draft.lat !== undefined && draft.lon !== undefined) {
      set({ near: km });
      return;
    }
    const point = await locate();
    if (point) set({ ...point, near: km });
    else setLocationFailed(true);
  };

  let content: ReactNode;
  if (view === 'budget') {
    content = (
      <Choices
        options={[
          { key: 'any', label: t('filters.any'), selected: draft.budget === undefined },
          ...BUDGET_STEPS.map((rsd) => ({
            key: String(rsd),
            label: t('filters.budgetFrom', { amount: format.money(rsdToPara(rsd)) }),
            selected: draft.budget === rsd,
          })),
        ]}
        onPick={(key) => {
          set({ budget: key === 'any' ? undefined : Number(key) });
          setView('filters');
        }}
      />
    );
  } else if (view === 'language') {
    content = (
      <Choices
        options={[
          { key: 'any', label: t('filters.any'), selected: !draft.langs },
          ...FEED_LANGUAGES.map((language) => ({
            key: language,
            label: t(`create.budget.langs.${language}`),
            selected: draft.langs?.length === 1 && draft.langs[0] === language,
          })),
        ]}
        onPick={(key) => {
          const language = FEED_LANGUAGES.find((item) => item === key);
          set({ langs: language ? [language] : undefined });
          setView('filters');
        }}
      />
    );
  } else {
    content = (
      <>
        <Radius cityId={city?.id ?? null} draft={draft} onPick={(km) => void pickRadius(km)} />
        {locationFailed && (
          <Banner tone="warn" role="alert">
            {t('feed.locationError')}
          </Banner>
        )}
        <Categories
          citySlug={city?.slug}
          selected={draft.categories}
          onToggle={(id) => set({ categories: toggle(draft.categories, id) })}
        />
        <Section title={t('filters.when')}>
          <Segmented<FeedWhen | 'any'>
            label={t('filters.when')}
            value={draft.when ?? 'any'}
            onChange={(when) => set({ when: when === 'any' ? undefined : when })}
            options={[
              { value: 'any', label: t('filters.anyTime') },
              { value: 'today', label: t('filters.today') },
              { value: 'week', label: t('filters.week') },
            ]}
          />
        </Section>
        <Section title={t('filters.extra')}>
          <Chips wrap>
            <Chip
              icon="zap"
              selected={draft.urgent === true}
              onClick={() => set({ urgent: draft.urgent ? undefined : true })}
            >
              {t('filters.urgentOnly')}
            </Chip>
            <Chip
              icon="camera"
              selected={draft.photos === true}
              onClick={() => set({ photos: draft.photos ? undefined : true })}
            >
              {t('filters.photosOnly')}
            </Chip>
          </Chips>
        </Section>
        {/* у шторки фон как у группы: рамка отделяет строки, как на макете */}
        <Group className="border border-line">
          <Row
            icon="wallet"
            title={t('filters.budget')}
            trailing={
              <span className="text-text2">
                {draft.budget === undefined
                  ? t('filters.any')
                  : t('filters.budgetFrom', { amount: format.money(rsdToPara(draft.budget)) })}
              </span>
            }
            chevron
            onClick={() => setView('budget')}
          />
          <Row
            icon="languages"
            title={t('filters.language')}
            trailing={
              <span className="text-text2">
                {draft.langs
                  ? draft.langs.map((language) => t(`create.budget.langs.${language}`)).join(', ')
                  : t('filters.any')}
              </span>
            }
            chevron
            onClick={() => setView('language')}
          />
        </Group>
        <div className="flex justify-center">
          <LinkButton onClick={() => setDraft(withoutFilters(draft))}>
            {t('filters.reset')}
          </LinkButton>
        </div>
        {!button.native && <div className={BUTTON_SPACE} aria-hidden="true" />}
      </>
    );
  }

  return (
    <Sheet
      open
      title={
        view === 'budget'
          ? t('filters.budget')
          : view === 'language'
            ? t('filters.language')
            : t('filters.title')
      }
      closeLabel={t('filters.close')}
      onClose={onClose}
    >
      {content}
    </Sheet>
  );
}

/** «Радиус от Лимана»: ближайший к точке район; без точки — просто «Радиус». */
function Radius({
  cityId,
  draft,
  onPick,
}: {
  cityId: number | null;
  draft: FeedSearch;
  onPick: (km: number) => void;
}) {
  const { t } = useTranslation('jobs');
  const locale = useLocale();
  const point =
    draft.lat !== undefined && draft.lon !== undefined ? { lat: draft.lat, lon: draft.lon } : null;
  const districts = useDistricts(point ? cityId : null, locale).data;
  const district = point && districts ? nearestDistrict(districts, point) : null;
  return (
    <Section
      title={district ? t('filters.radiusFrom', { place: district.name }) : t('filters.radius')}
    >
      <Chips wrap>
        {RADII.map((km) => (
          <Chip key={km} selected={draft.near === km} onClick={() => onPick(km)}>
            {t('filters.km', { km })}
          </Chip>
        ))}
      </Chips>
    </Section>
  );
}

/** Разделы каталога чипами; выбранная услуга не из разделов (с Главной, из ссылки) — тоже чип. */
function Categories({
  citySlug,
  selected,
  onToggle,
}: {
  citySlug: string | undefined;
  selected: number[] | undefined;
  onToggle: (id: number) => void;
}) {
  const { t } = useTranslation('jobs');
  const locale = useLocale();
  const tree: CategoryOut[] = useCategories(locale, citySlug).data ?? [];
  const extra = (selected ?? [])
    .filter((id) => !tree.some((section) => section.id === id))
    .map((id) => findCategory(tree, id))
    .filter((node): node is CategoryOut => node !== null);
  return (
    <Section title={t('filters.categories')}>
      <Chips wrap>
        {[...tree, ...extra].map((node) => (
          <Chip
            key={node.id}
            selected={selected?.includes(node.id) ?? false}
            onClick={() => onToggle(node.id)}
          >
            {node.name}
          </Chip>
        ))}
      </Chips>
    </Section>
  );
}

/** Второй вид шторки: один вариант из списка, выбранный — с галочкой. */
function Choices({
  options,
  onPick,
}: {
  options: { key: string; label: string; selected: boolean }[];
  onPick: (key: string) => void;
}) {
  return (
    <Group className="border border-line">
      {options.map((option) => (
        <Row
          key={option.key}
          title={option.label}
          trailing={option.selected ? <Icon name="check" className="text-accent" /> : undefined}
          onClick={() => onPick(option.key)}
        />
      ))}
    </Group>
  );
}

/** Группа фильтров с видимой подписью (.lbl на макете S14). */
function Section({ title, children }: { title: string; children: ReactNode }) {
  const id = useId();
  return (
    <div role="group" aria-labelledby={id} className="flex flex-col gap-2">
      <span id={id} className="text-sm font-semibold">
        {title}
      </span>
      {children}
    </div>
  );
}
