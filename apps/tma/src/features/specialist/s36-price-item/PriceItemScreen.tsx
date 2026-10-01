// S36 Позиция прайса (DEVELOPMENT_PLAN 2.11): название, группа (категория профиля), цена — фикс,
// «от» или за час, длительность, описание → POST /me/profile/services или PATCH (только
// изменённое; убранное — через `clear`); «Удалить позицию» — после подтверждения. Ориентир цены
// под полем — v1. Типы «от и до», «за единицу», «договорная» мастер не предлагает, но позицию
// такого типа (из API) правит, не меняя тип.
import type {
  CategoryOut,
  PriceType,
  ProfileOut,
  ServiceOut,
  ServiceUpdateIn,
  ServiceUpdateInClearItem,
  ServicesOut,
} from '@sosed/api-client';
import {
  getPricingListMyServicesQueryKey,
  pricingAddMyService,
  pricingChangeMyService,
  pricingRemoveMyService,
  usePricingListMyServices,
} from '@sosed/api-client';
import { myProfileQueryKey, useCategories, useMyProfile } from '@sosed/hooks';
import { useFormat, useLocale, useTranslation } from '@sosed/i18n';
import { useBackButton, usePlatform } from '@sosed/platform';
import { Button, Field, Heading, Icon, Input, Segmented, Textarea, cx } from '@sosed/ui-web';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useParams, useRouter } from '@tanstack/react-router';
import type { SelectHTMLAttributes } from 'react';
import { useEffect, useId, useRef, useState } from 'react';

import { LoadState } from '../shared/LoadState.tsx';
import { SaveError } from '../shared/SaveError.tsx';
import { useStepButton } from '../shared/flow.ts';
import { ACCOUNT_PATH, CABINET_PATHS } from '../shared/paths.ts';
import { DURATIONS, categoryNames } from '../shared/prices.ts';

/** MAX_TITLE и MAX_DESCRIPTION позиции (backend pricing/domain/service.py). */
const MAX_TITLE = 120;
const MAX_DESCRIPTION = 1000;
/** Цена — до 999 999 999 RSD (MAX_PRICE прайса — миллиард). */
const PRICE_DIGITS = 9;
const PARA_PER_DINAR = 100;
/** Типы цены артборда S36. */
const TYPES: readonly PriceType[] = ['fixed', 'from', 'hourly'];

const SELECT =
  'h-12 w-full appearance-none rounded-field border border-field bg-surface pr-10 pl-3.5 text-input text-text outline-none focus-visible:border-accent focus-visible:ring-3 focus-visible:ring-accent-soft';

/** Нативный выбор (на телефоне — системный список) со стрелкой артборда. */
function Select({ children, ...rest }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <div className="relative">
      <select {...rest} className={SELECT}>
        {children}
      </select>
      <Icon
        name="chev-down"
        className="pointer-events-none absolute top-1/2 right-3.5 -translate-y-1/2 text-text2"
      />
    </div>
  );
}

export function PriceItemScreen() {
  const { t } = useTranslation('specialist');
  const router = useRouter();
  const params: { serviceId?: string } = useParams({ strict: false });
  const profile = useMyProfile();
  const services = usePricingListMyServices({ query: { enabled: Boolean(profile.data) } });
  const categories = useCategories(useLocale());
  const back = () => {
    if (router.history.canGoBack()) router.history.back();
    else void router.navigate({ to: CABINET_PATHS.prices, replace: true });
  };
  useBackButton(back);
  const service = services.data?.items.find((item) => item.id === params.serviceId);
  useEffect(() => {
    if (profile.data === null) void router.navigate({ to: ACCOUNT_PATH, replace: true });
    // позицию удалили или её нет — к прайсу
    else if (params.serviceId && services.data && !service) {
      void router.navigate({ to: CABINET_PATHS.prices, replace: true });
    }
  }, [params.serviceId, profile.data, router, service, services.data]);

  if (profile.data && services.data && categories.data && (!params.serviceId || service)) {
    return (
      <PriceItemForm
        profile={profile.data}
        service={service ?? null}
        tree={categories.data}
        onDone={back}
      />
    );
  }
  const loads = [profile, services, categories];
  const failed = loads.find((load) => load.isError);
  return (
    <section className="flex flex-col gap-3 px-4 pt-3 pb-6">
      <Heading variant="h2" as="h1">
        {t(params.serviceId ? 'price.title' : 'price.titleNew')}
      </Heading>
      <LoadState
        error={failed ? failed.error : null}
        onRetry={() => {
          for (const load of loads) if (load.isError) void load.refetch();
        }}
        retrying={loads.some((load) => load.isFetching)}
      />
    </section>
  );
}

function PriceItemForm({
  profile,
  service,
  tree,
  onDone,
}: {
  profile: ProfileOut;
  /** null — новая позиция. */
  service: ServiceOut | null;
  tree: CategoryOut[];
  onDone: () => void;
}) {
  const { t } = useTranslation('specialist');
  const { number } = useFormat();
  const platform = usePlatform();
  const queryClient = useQueryClient();
  const groupId = useId();
  const durationId = useId();
  const names = categoryNames(tree);
  const [title, setTitle] = useState(service?.title ?? '');
  const [categoryId, setCategoryId] = useState<number | null>(
    service ? service.category_id : (profile.category_ids[0] ?? null),
  );
  const [type, setType] = useState<PriceType>(service?.price_type ?? 'fixed');
  const [amount, setAmount] = useState(
    service?.price_min ? String(Math.round(service.price_min.amount / PARA_PER_DINAR)) : '',
  );
  const [duration, setDuration] = useState<number | null>(service?.duration_min ?? null);
  const [description, setDescription] = useState(service?.description ?? '');
  // незаполненное подсвечиваем после первого нажатия «Сохранить»
  const [checked, setChecked] = useState(false);
  // Idempotency-Key новой позиции: повтор после потерянного ответа не добавит вторую
  const key = useRef<string | null>(null);
  const priced = type !== 'negotiable';
  const missing = { title: title.trim() === '', amount: priced && !(Number(amount) > 0) };
  // группы — категории профиля; позиция с чужой категорией (из API) её не теряет
  const groups = [
    ...new Set([...profile.category_ids, ...(categoryId === null ? [] : [categoryId])]),
  ];
  const types = TYPES.includes(type) ? TYPES : [...TYPES, type];
  const durations =
    duration === null || DURATIONS.some((value) => value === duration)
      ? DURATIONS
      : [...DURATIONS, duration];

  const cache = (items: (list: ServiceOut[]) => ServiceOut[]) => {
    queryClient.setQueryData<ServicesOut>(getPricingListMyServicesQueryKey(), (list) =>
      list ? { items: items(list.items) } : list,
    );
    // полнота профиля зависит от прайса — перечитываем
    void queryClient.invalidateQueries({ queryKey: myProfileQueryKey() });
  };

  const save = useMutation({
    mutationFn: async () => {
      const para = priced ? Number(amount) * PARA_PER_DINAR : null;
      if (!service) {
        key.current ??= crypto.randomUUID();
        const created = await pricingAddMyService(
          {
            title: title.trim(),
            price_type: type,
            price_min: para,
            category_id: categoryId,
            duration_min: duration,
            description: description.trim() || null,
          },
          { 'Idempotency-Key': key.current },
        );
        cache((items) => [...items, created]);
        return;
      }
      const patch: ServiceUpdateIn = {};
      const clear: ServiceUpdateInClearItem[] = [];
      if (title.trim() !== service.title) patch.title = title.trim();
      if (type !== service.price_type) patch.price_type = type;
      if (para !== null && para !== service.price_min?.amount) patch.price_min = para;
      if (categoryId !== service.category_id) {
        if (categoryId === null) clear.push('category_id');
        else patch.category_id = categoryId;
      }
      if (duration !== service.duration_min) {
        if (duration === null) clear.push('duration_min');
        else patch.duration_min = duration;
      }
      if (description.trim() !== (service.description ?? '')) {
        if (description.trim() === '') clear.push('description');
        else patch.description = description.trim();
      }
      if (clear.length > 0) patch.clear = clear;
      if (Object.keys(patch).length === 0) return;
      const changed = await pricingChangeMyService(service.id, patch);
      cache((items) => items.map((item) => (item.id === changed.id ? changed : item)));
    },
    onSuccess: () => {
      platform.haptics.notification('success');
      onDone();
    },
  });

  const remove = useMutation({
    mutationFn: async (target: ServiceOut) => {
      await pricingRemoveMyService(target.id);
      cache((items) => items.filter((item) => item.id !== target.id));
    },
    onSuccess: onDone,
  });

  useStepButton({
    text: t('price.save'),
    onClick: () => {
      if (save.isPending || remove.isPending) return;
      if (missing.title || missing.amount) {
        setChecked(true);
        platform.haptics.notification('error');
        return;
      }
      save.mutate();
    },
    loading: save.isPending,
  });

  const edit = (apply: () => void) => {
    key.current = null;
    apply();
  };
  const confirmRemove = async (target: ServiceOut) => {
    if (await platform.confirm(t('price.deleteConfirm', { title: target.title }))) {
      remove.mutate(target);
    }
  };

  return (
    <section className="flex flex-col gap-3 px-4 pt-3 pb-6">
      <Heading variant="h2" as="h1">
        {t(service ? 'price.title' : 'price.titleNew')}
      </Heading>
      <Field
        label={t('price.name')}
        error={checked && missing.title ? t('price.nameMissing') : undefined}
      >
        <Input
          value={title}
          maxLength={MAX_TITLE}
          placeholder={t('price.namePlaceholder')}
          onChange={(event) => edit(() => setTitle(event.target.value))}
        />
      </Field>
      <div className="flex flex-col gap-1.5">
        <label htmlFor={groupId} className="text-sm font-semibold">
          {t('price.group')}
        </label>
        <Select
          id={groupId}
          value={categoryId ?? ''}
          onChange={(event) =>
            edit(() => setCategoryId(event.target.value ? Number(event.target.value) : null))
          }
        >
          {groups.map((id) => (
            <option key={id} value={id}>
              {names.get(id) ?? t('price.noGroup')}
            </option>
          ))}
          <option value="">{t('price.noGroup')}</option>
        </Select>
      </div>
      <div className="flex flex-col gap-1.5">
        <span aria-hidden="true" className="text-sm font-semibold">
          {t('price.type')}
        </span>
        <Segmented
          label={t('price.type')}
          value={type}
          onChange={(next) => edit(() => setType(next))}
          options={types.map((value) => ({ value, label: t(`price.${value}`) }))}
        />
        {priced && (
          <Input
            inputMode="numeric"
            value={amount && number(Number(amount))}
            suffix="RSD"
            aria-label={t('price.amount')}
            invalid={checked && missing.amount}
            onChange={(event) =>
              edit(() => setAmount(event.target.value.replace(/\D/g, '').slice(0, PRICE_DIGITS)))
            }
          />
        )}
        {checked && missing.amount && (
          <p role="alert" className="m-0 text-cap text-danger">
            {t('price.amountMissing')}
          </p>
        )}
      </div>
      <div className="flex flex-col gap-1.5">
        <label htmlFor={durationId} className="text-sm font-semibold">
          {t('price.duration')}
        </label>
        <Select
          id={durationId}
          value={duration ?? ''}
          onChange={(event) =>
            edit(() => setDuration(event.target.value ? Number(event.target.value) : null))
          }
        >
          <option value="">{t('price.durationNone')}</option>
          {durations.map((minutes) => (
            <option key={minutes} value={minutes}>
              {DURATIONS.some((value) => value === minutes)
                ? t(`price.durations.${minutes as (typeof DURATIONS)[number]}`)
                : number(minutes)}
            </option>
          ))}
        </Select>
      </div>
      <Field
        label={t('price.description')}
        hint={t('price.descriptionHint', { count: description.length, max: MAX_DESCRIPTION })}
      >
        <Textarea
          rows={3}
          value={description}
          maxLength={MAX_DESCRIPTION}
          placeholder={t('price.descriptionPlaceholder')}
          onChange={(event) => edit(() => setDescription(event.target.value))}
        />
      </Field>
      {service && (
        <Button
          variant="danger"
          full
          icon="trash"
          disabled={remove.isPending}
          aria-busy={remove.isPending}
          onClick={() => void confirmRemove(service)}
          className={cx(remove.isPending && 'opacity-70')}
        >
          {t('price.delete')}
        </Button>
      )}
      {(save.isError || remove.isError) && <SaveError error={save.error ?? remove.error} />}
    </section>
  );
}
