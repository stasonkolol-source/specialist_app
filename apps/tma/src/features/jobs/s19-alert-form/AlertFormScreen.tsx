// S19 Подписка на заявки (DEVELOPMENT_PLAN 5.7): категории — разделы каталога чипами (и выбранная
// услуга не из разделов), «Где» — весь город или радиус 1/3/5/10 км от точки исполнителя (её
// спрашивает Telegram; подпись — ближайший район), «Бюджет от», «Сразу / Раз в день», «Только
// срочные», язык общения (шторка выбора) и тихие часы — общая настройка уведомлений (S43).
// MainButton «Сохранить подписку»: новая — с ключом идемпотентности на тело формы, правка —
// условия целиком. Новая открывается и из шторки фильтров S14 («Сохранить как подписку»): фильтры
// ленты — уже в форме. После сохранения — список S18: там же, если боту нельзя писать, — «Присылать
// новые заявки в бот?». Подписка, созданная не здесь, с районами — районы остаются, пока «Где» не
// меняли.
import type { CategoryOut, JobAlertOut } from '@sosed/api-client';
import { ApiError, useNotificationsGetNotificationSettings } from '@sosed/api-client';
import {
  nearestDistrict,
  selectableDistricts,
  useCategories,
  useCreateAlert,
  useDistricts,
  useJobAlerts,
  useUpdateAlert,
  useUpdateNotificationSettings,
} from '@sosed/hooks';
import { moneyInput, useLocale, useTranslation } from '@sosed/i18n';
import { useBackButton } from '@sosed/platform';
import {
  Banner,
  Chip,
  Chips,
  EmptyState,
  Field,
  FieldSkeleton,
  Group,
  Heading,
  Icon,
  Input,
  Row,
  Segmented,
  Sheet,
  Switch,
  Text,
} from '@sosed/ui-web';
import { useParams, useRouter, useSearch } from '@tanstack/react-router';
import type { ReactNode } from 'react';
import { useId, useRef, useState } from 'react';

import type { AlertForm } from '../shared/alerts.ts';
import { criteriaIn, formFromFeed, formOf, isFeedLanguage, urgentOnly } from '../shared/alerts.ts';
import { findCategory } from '../shared/categories.ts';
import { useFeedCity } from '../shared/city.ts';
import { FEED_LANGUAGES, RADII, toggle } from '../shared/feed.ts';
import { useStepButton } from '../shared/flow.ts';
import { useLocate } from '../shared/location.ts';
import type { AlertFormSearch } from '../shared/paths.ts';
import { JOBS_PATHS } from '../shared/paths.ts';

export function AlertFormScreen() {
  const { t } = useTranslation('jobs');
  const { alertId } = useParams({ strict: false });
  const search: AlertFormSearch = useSearch({ strict: false });
  const alerts = useJobAlerts(alertId !== undefined);
  const editing = alertId ? (alerts.data?.items.find((item) => item.id === alertId) ?? null) : null;

  if (alertId && !alerts.data) {
    return (
      <section className="flex flex-col gap-4 px-4 pt-3 pb-6" aria-busy="true">
        <FieldSkeleton />
        <FieldSkeleton />
        <FieldSkeleton />
      </section>
    );
  }
  if (alertId && !editing) {
    return (
      <section className="px-4 pt-6">
        <EmptyState as="h1" icon="bell" title={t('alerts.form.missing')} />
      </section>
    );
  }
  return (
    <Form
      key={editing?.id ?? 'new'}
      alert={editing}
      initial={editing ? formOf(editing) : formFromFeed(search)}
      fromFeed={search.from === 'feed'}
    />
  );
}

function Form({
  alert,
  initial,
  fromFeed,
}: {
  alert: JobAlertOut | null;
  initial: AlertForm;
  fromFeed: boolean;
}) {
  const { t } = useTranslation('jobs');
  const locale = useLocale();
  const router = useRouter();
  const feedCity = useFeedCity();
  const cityId = alert?.criteria.city_id ?? feedCity?.id ?? null;
  const [form, setForm] = useState<AlertForm>(initial);
  const [checked, setChecked] = useState(false);
  const [languages, setLanguages] = useState(false);
  const [locationFailed, setLocationFailed] = useState(false);
  const attempt = useRef<{ body: string; key: string } | null>(null);
  const locate = useLocate();
  const create = useCreateAlert();
  const update = useUpdateAlert();
  const failed = create.error ?? update.error;
  const set = (patch: Partial<AlertForm>) => setForm((current) => ({ ...current, ...patch }));
  const languagesLabel = useLanguagesLabel(form.langs);

  // из S18 — назад к нему же; из шторки ленты S14 — к списку подписок вместо формы
  const leave = () => {
    if (!fromFeed && router.history.canGoBack()) router.history.back();
    else void router.navigate({ to: JOBS_PATHS.alerts, replace: true });
  };
  useBackButton(languages ? () => setLanguages(false) : leave);

  const save = async () => {
    setChecked(true);
    const criteria = cityId !== null ? criteriaIn(form, cityId) : null;
    if (!criteria || create.isPending || update.isPending) return;
    try {
      if (alert) {
        await update.mutateAsync({
          alertId: alert.id,
          body: { criteria, delivery: form.delivery },
        });
      } else {
        const body = { criteria, delivery: form.delivery };
        const json = JSON.stringify(body);
        if (attempt.current?.body !== json)
          attempt.current = { body: json, key: crypto.randomUUID() };
        await create.mutateAsync({ body, key: attempt.current.key });
      }
      leave();
    } catch {
      // ошибка — баннером
    }
  };
  useStepButton({
    text: t('alerts.form.save'),
    loading: create.isPending || update.isPending,
    visible: !languages,
    onClick: () => void save(),
  });

  const pickRadius = async (km: number) => {
    setLocationFailed(false);
    if (form.point) {
      set({ area: 'radius', km });
      return;
    }
    const point = await locate();
    if (point) set({ area: 'radius', km, point });
    else setLocationFailed(true);
  };

  const detail = failed instanceof ApiError && failed.status < 500 ? failed.problem.detail : null;
  return (
    <section className="flex flex-col gap-3.5 px-4 pt-3 pb-6">
      <div className="flex flex-col gap-1">
        <Heading variant="h2" as="h1">
          {alert ? t('alerts.form.titleEdit') : t('alerts.form.titleNew')}
        </Heading>
        <Text variant="cap">{t('alerts.form.lead')}</Text>
      </div>
      {failed && (
        <Banner tone="danger" role="alert">
          {detail ?? t('alerts.error')}
        </Banner>
      )}
      <Categories
        selected={form.categories}
        missing={checked && form.categories.length === 0}
        onToggle={(id) => set({ categories: toggle(form.categories, id) ?? [] })}
      />
      <Area
        cityId={cityId}
        form={form}
        onCity={() => set({ area: 'city' })}
        onRadius={(km) => void pickRadius(km)}
      />
      {locationFailed && (
        <Banner tone="warn" role="alert">
          {t('feed.locationError')}
        </Banner>
      )}
      <Field label={t('alerts.form.budget')}>
        <Input
          inputMode="numeric"
          suffix="RSD"
          value={moneyInput(form.budget, locale)}
          placeholder={t('alerts.form.budgetPlaceholder')}
          onChange={(event) => set({ budget: moneyInput(event.target.value, locale) })}
        />
      </Field>
      <Section title={t('alerts.form.delivery')}>
        <Segmented<AlertForm['delivery']>
          label={t('alerts.form.delivery')}
          value={form.delivery}
          onChange={(delivery) => set({ delivery })}
          options={[
            { value: 'instant', label: t('alerts.form.instant') },
            { value: 'digest', label: t('alerts.form.digest') },
          ]}
        />
      </Section>
      <Group className="border border-line">
        <Row
          leading={<Icon name="zap" className="shrink-0 text-urgent" />}
          title={t('alerts.form.urgentOnly')}
          trailing={
            <Switch
              checked={urgentOnly(form)}
              label={t('alerts.form.urgentOnly')}
              onChange={(on) => set({ urgencies: on ? ['asap'] : [] })}
            />
          }
        />
        <Row
          leading={<Icon name="languages" className="shrink-0" />}
          title={t('alerts.form.language')}
          trailing={<span className="text-text2">{languagesLabel}</span>}
          chevron
          onClick={() => setLanguages(true)}
        />
        <QuietRow />
      </Group>
      {languages && (
        <LanguageSheet
          selected={form.langs}
          onPick={(langs) => {
            set({ langs });
            setLanguages(false);
          }}
          onClose={() => setLanguages(false)}
        />
      )}
    </section>
  );
}

/** Разделы каталога чипами; выбранная услуга не из разделов (из фильтров ленты) — тоже чип. */
function Categories({
  selected,
  missing,
  onToggle,
}: {
  selected: number[];
  missing: boolean;
  onToggle: (id: number) => void;
}) {
  const { t } = useTranslation('jobs');
  const locale = useLocale();
  const tree: CategoryOut[] = useCategories(locale).data ?? [];
  const extra = selected
    .filter((id) => !tree.some((section) => section.id === id))
    .map((id) => findCategory(tree, id))
    .filter((node): node is CategoryOut => node !== null);
  return (
    <Section title={t('alerts.form.categories')}>
      <Chips wrap>
        {[...tree, ...extra].map((node) => (
          <Chip
            key={node.id}
            icon={selected.includes(node.id) ? 'check' : undefined}
            selected={selected.includes(node.id)}
            onClick={() => onToggle(node.id)}
          >
            {node.name}
          </Chip>
        ))}
      </Chips>
      {missing && (
        <p role="alert" className="m-0 text-cap text-danger">
          {t('alerts.form.missingCategories')}
        </p>
      )}
    </Section>
  );
}

/** «Где»: весь город или радиус от точки исполнителя — подписан ближайшим районом. */
function Area({
  cityId,
  form,
  onCity,
  onRadius,
}: {
  cityId: number | null;
  form: AlertForm;
  onCity: () => void;
  onRadius: (km: number) => void;
}) {
  const { t } = useTranslation('jobs');
  const locale = useLocale();
  const districts = useDistricts(cityId, locale).data;
  const near = form.point && districts ? nearestDistrict(districts, form.point) : null;
  const named =
    form.area === 'districts' && districts
      ? selectableDistricts(districts, locale)
          .filter((district) => form.districts.includes(district.id))
          .map((district) => district.name)
          .join(', ')
      : '';
  return (
    <Section
      title={near ? t('alerts.form.radiusFrom', { place: near.name }) : t('alerts.form.radius')}
    >
      <Chips wrap>
        <Chip selected={form.area === 'city'} onClick={onCity}>
          {t('alerts.form.city')}
        </Chip>
        {form.area === 'districts' && named && <Chip selected>{named}</Chip>}
        {RADII.map((km) => (
          <Chip
            key={km}
            selected={form.area === 'radius' && form.km === km}
            onClick={() => onRadius(km)}
          >
            {t('filters.km', { km })}
          </Chip>
        ))}
      </Chips>
    </Section>
  );
}

/** Тихие часы — общая настройка уведомлений: тот же переключатель, что на S43. */
function QuietRow() {
  const { t } = useTranslation('jobs');
  const settings = useNotificationsGetNotificationSettings();
  const change = useUpdateNotificationSettings();
  const quiet = settings.data?.quiet_hours;
  if (!quiet) return null;
  const label = t('alerts.form.quiet', {
    from: quiet.start.slice(0, 5),
    to: quiet.end.slice(0, 5),
  });
  return (
    <Row
      leading={<Icon name="bell" className="shrink-0" />}
      title={label}
      subtitle={t('alerts.form.quietHint')}
      trailing={
        <Switch
          checked={quiet.enabled}
          label={label}
          onChange={(on) => change.mutate({ quiet: on })}
        />
      }
    />
  );
}

function useLanguagesLabel(langs: readonly string[]): string {
  const { t } = useTranslation('jobs');
  if (langs.length === 0) return t('alerts.form.anyLanguage');
  return langs
    .map((code) => (isFeedLanguage(code) ? t(`create.budget.langs.${code}`) : code))
    .join(', ');
}

/** Язык общения: любой или один из языков заявок (как во фильтре ленты S14). */
function LanguageSheet({
  selected,
  onPick,
  onClose,
}: {
  selected: readonly string[];
  onPick: (langs: string[]) => void;
  onClose: () => void;
}) {
  const { t } = useTranslation('jobs');
  const options = [
    { key: 'any', label: t('alerts.form.anyLanguage'), on: selected.length === 0 },
    ...FEED_LANGUAGES.map((language) => ({
      key: language,
      label: t(`create.budget.langs.${language}`),
      on: selected.length === 1 && selected[0] === language,
    })),
  ];
  return (
    <Sheet open title={t('alerts.form.language')} closeLabel={t('filters.close')} onClose={onClose}>
      <Group className="border border-line">
        {options.map((option) => (
          <Row
            key={option.key}
            title={option.label}
            trailing={option.on ? <Icon name="check" className="text-accent" /> : undefined}
            onClick={() => onPick(option.key === 'any' ? [] : [option.key])}
          />
        ))}
      </Group>
    </Sheet>
  );
}

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
