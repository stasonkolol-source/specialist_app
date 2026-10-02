// S06 Фильтры каталога (DEVELOPMENT_PLAN 4.4): шторка поверх выдачи S05. Изменения — черновик:
// «Показать N» (MainButton) применяет их к адресу выдачи, «Назад» и крестик закрывают шторку без
// изменений. N считает сервер тем же разбором запроса, что и выдачу; пока человек нажимает чипы,
// счёт ждёт (лимит гостя — 60 запросов в минуту). «Ближе» спрашивает местоположение.
// Категория выбирается вторым видом шторки; «только проверенные» — с бейджами v1.
import type { CategoryOut, CityOut } from '@sosed/api-client';
import { tokens } from '@sosed/design-tokens';
import { selectableDistricts, useCategories, useDistricts, useSpecialistCount } from '@sosed/hooks';
import { useLocale, useTranslation } from '@sosed/i18n';
import {
  useBackButton,
  useBottomButtonState,
  useColorScheme,
  useMainButton,
} from '@sosed/platform';
import {
  Banner,
  Chip,
  Chips,
  Field,
  Group,
  Icon,
  Input,
  LinkButton,
  Row,
  Segmented,
  Sheet,
  Switch,
} from '@sosed/ui-web';
import type { ReactNode } from 'react';
import { Fragment, useId, useMemo, useState } from 'react';

import { useDebounced } from '../shared/debounce.ts';
import { useLocate } from '../shared/location.ts';
import type { Language, ResultSort, ResultsSearch, WorkMode } from '../shared/paths.ts';
import { LANGUAGES, RESULT_SORTS, WORK_MODES } from '../shared/paths.ts';
import { toQuery, withoutFilters } from '../shared/query.ts';

const DISTRICTS_FIRST = 4;
const COUNT_DELAY_MS = 400;
/** Место под кнопку «Показать N» в браузере: AppShell рисует её поверх шторки. */
const BUTTON_SPACE = 'h-19';

export interface FiltersSheetProps {
  search: ResultsSearch;
  city: CityOut | null;
  onClose: () => void;
  onApply: (search: ResultsSearch) => void;
}

function toggle<T>(list: readonly T[] | undefined, value: T): T[] | undefined {
  const next = list?.includes(value)
    ? list.filter((item) => item !== value)
    : [...(list ?? []), value];
  return next.length > 0 ? next : undefined;
}

export function FiltersSheet({ search, city, onClose, onApply }: FiltersSheetProps) {
  const { t } = useTranslation('catalog');
  const [draft, setDraft] = useState<ResultsSearch>(search);
  const [view, setView] = useState<'filters' | 'category'>('filters');
  const [allDistricts, setAllDistricts] = useState(false);
  const [locationFailed, setLocationFailed] = useState(false);
  const locate = useLocate();
  const scheme = useColorScheme();
  const palette = tokens.color[scheme];
  const button = useBottomButtonState('main');

  const query = useMemo(() => (city ? toQuery(draft, city.id) : null), [draft, city]);
  const count = useSpecialistCount(useDebounced(query, COUNT_DELAY_MS));
  const found = count.data;
  const text = !found
    ? t('filters.title')
    : found.capped
      ? t('filters.showMore', { count: found.count })
      : found.count === 0
        ? t('filters.nobody')
        : t('filters.show', { count: found.count });
  useMainButton({
    text,
    onClick: () => onApply(draft),
    visible: view === 'filters',
    enabled: found?.count !== 0,
    color: palette.accent,
    textColor: palette['accent-ink'],
  });
  useBackButton(() => (view === 'category' ? setView('filters') : onClose()));

  const set = (patch: Partial<ResultsSearch>) => setDraft((current) => ({ ...current, ...patch }));
  const sortBy = async (sort: ResultSort) => {
    setLocationFailed(false);
    if (sort !== 'distance' || draft.lat !== undefined) {
      set({ sort: sort === 'relevance' ? undefined : sort });
      return;
    }
    const point = await locate();
    if (point) set({ sort, ...point });
    else setLocationFailed(true);
  };

  return (
    <Sheet open title={t('filters.title')} closeLabel={t('filters.close')} onClose={onClose}>
      {view === 'category' ? (
        <CategoryPicker
          selected={draft.category}
          citySlug={city?.slug}
          onPick={(category) => {
            set({ category });
            setView('filters');
          }}
        />
      ) : (
        <>
          <Section title={t('filters.sort')}>
            <Segmented<ResultSort>
              label={t('filters.sort')}
              value={draft.sort ?? 'relevance'}
              onChange={(sort) => void sortBy(sort)}
              options={RESULT_SORTS.map((sort) => ({
                value: sort,
                label: t(
                  sort === 'relevance'
                    ? 'filters.sortRelevance'
                    : sort === 'distance'
                      ? 'filters.sortDistance'
                      : 'filters.sortRating',
                ),
              }))}
            />
          </Section>
          {locationFailed && (
            <Banner tone="warn" role="alert">
              {t('results.locationError')}
            </Banner>
          )}
          <Districts
            cityId={city?.id ?? null}
            selected={draft.districts}
            expanded={allDistricts}
            onExpand={() => setAllDistricts(true)}
            onChange={(districts) => set({ districts })}
          />
          <Field label={t('filters.priceMax')}>
            <Input
              inputMode="numeric"
              suffix="RSD"
              value={draft.price === undefined ? '' : String(draft.price)}
              onChange={(event) => {
                const digits = event.target.value.replace(/\D/g, '');
                set({ price: digits ? Number(digits) : undefined });
              }}
            />
          </Field>
          <Section title={t('filters.language')}>
            <Chips wrap>
              <Chip selected={!draft.langs} onClick={() => set({ langs: undefined })}>
                {t('filters.anyLanguage')}
              </Chip>
              {LANGUAGES.map((language: Language) => (
                <Chip
                  key={language}
                  selected={draft.langs?.includes(language) ?? false}
                  onClick={() => set({ langs: toggle(draft.langs, language) })}
                >
                  {t(`filters.languages.${language}`)}
                </Chip>
              ))}
            </Chips>
          </Section>
          <Section title={t('filters.workMode')}>
            <Chips wrap>
              {WORK_MODES.map((mode: WorkMode) => (
                <Chip
                  key={mode}
                  selected={draft.modes?.includes(mode) ?? false}
                  onClick={() => set({ modes: toggle(draft.modes, mode) })}
                >
                  {t(`filters.workModes.${mode}`)}
                </Chip>
              ))}
            </Chips>
          </Section>
          {/* у шторки фон как у группы: рамка отделяет строки, как на макете */}
          <Group className="border border-line">
            <CategoryRow
              selected={draft.category}
              citySlug={city?.slug}
              onOpen={() => setView('category')}
            />
            <Row
              title={t('filters.availableToday')}
              trailing={
                <Switch
                  label={t('filters.availableToday')}
                  checked={draft.today === true}
                  onChange={(checked) => set({ today: checked || undefined })}
                />
              }
            />
            <Row
              title={t('filters.withReviews')}
              trailing={
                <Switch
                  label={t('filters.withReviews')}
                  checked={draft.reviews === true}
                  onChange={(checked) => set({ reviews: checked || undefined })}
                />
              }
            />
          </Group>
          <div className="flex justify-center">
            <LinkButton onClick={() => setDraft(withoutFilters(draft))}>
              {t('filters.reset')}
            </LinkButton>
          </div>
          {!button.native && <div className={BUTTON_SPACE} aria-hidden="true" />}
        </>
      )}
    </Sheet>
  );
}

function Districts({
  cityId,
  selected,
  expanded,
  onExpand,
  onChange,
}: {
  cityId: number | null;
  selected: number[] | undefined;
  expanded: boolean;
  onExpand: () => void;
  onChange: (districts: number[] | undefined) => void;
}) {
  const { t } = useTranslation('catalog');
  const locale = useLocale();
  const districts = selectableDistricts(useDistricts(cityId, locale).data ?? [], locale);
  // выбранные районы видны всегда, даже если они за «Ещё»
  const shown = expanded
    ? districts
    : districts.filter(
        (district, index) => index < DISTRICTS_FIRST || selected?.includes(district.id),
      );
  const hidden = districts.length - shown.length;
  return (
    <Section title={t('filters.districts')}>
      <Chips wrap>
        <Chip selected={!selected} onClick={() => onChange(undefined)}>
          {t('filters.wholeCity')}
        </Chip>
        {shown.map((district) => (
          <Chip
            key={district.id}
            selected={selected?.includes(district.id) ?? false}
            onClick={() => onChange(toggle(selected, district.id))}
          >
            {district.name}
          </Chip>
        ))}
        {hidden > 0 && (
          <Chip expanded={false} onClick={onExpand}>
            {t('filters.moreDistricts', { count: hidden })}
          </Chip>
        )}
      </Chips>
    </Section>
  );
}

/** Группа фильтров с видимой подписью (.lbl на макете S06). */
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

function findCategory(tree: readonly CategoryOut[], id: number): CategoryOut | undefined {
  for (const node of tree) {
    if (node.id === id) return node;
    const child = findCategory(node.children, id);
    if (child) return child;
  }
  return undefined;
}

function CategoryRow({
  selected,
  citySlug,
  onOpen,
}: {
  selected: number | undefined;
  citySlug: string | undefined;
  onOpen: () => void;
}) {
  const { t } = useTranslation('catalog');
  const locale = useLocale();
  const tree = useCategories(locale, citySlug).data ?? [];
  const name = selected === undefined ? undefined : findCategory(tree, selected)?.name;
  return (
    <Row
      title={t('filters.category')}
      trailing={<span className="text-text2">{name ?? t('filters.anyCategory')}</span>}
      chevron
      onClick={onOpen}
    />
  );
}

function CategoryPicker({
  selected,
  citySlug,
  onPick,
}: {
  selected: number | undefined;
  citySlug: string | undefined;
  onPick: (category: number | undefined) => void;
}) {
  const { t } = useTranslation('catalog');
  const locale = useLocale();
  const tree = useCategories(locale, citySlug).data ?? [];
  const mark = (id: number | undefined) =>
    selected === id ? <Icon name="check" className="text-accent" /> : undefined;
  return (
    <Group>
      <Row
        title={t('filters.anyCategory')}
        trailing={mark(undefined)}
        onClick={() => onPick(undefined)}
      />
      {tree.map((node) => (
        <Fragment key={node.id}>
          <Row
            title={<span className="font-semibold">{node.name}</span>}
            trailing={mark(node.id)}
            onClick={() => onPick(node.id)}
          />
          {node.children.map((child) => (
            <Row
              key={child.id}
              inset
              title={child.name}
              trailing={mark(child.id)}
              onClick={() => onPick(child.id)}
            />
          ))}
        </Fragment>
      ))}
    </Group>
  );
}
