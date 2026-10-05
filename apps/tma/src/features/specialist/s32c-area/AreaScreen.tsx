// S32c «Где и почём работаете», шаг 3 из 3 (DEVELOPMENT_PLAN 2.9): районы города профиля (PUT
// /me/profile/areas), формат и радиус выезда (PATCH /me/profile), первая позиция прайса (POST
// /me/profile/services, а если она уже есть — PATCH) и «Отправить на проверку» (POST
// /me/profile/submit). Районы нужны, когда специалист выезжает; «Весь Нови-Сад» отмечает их все
// одним нажатием и у выезжающего без районов включён сразу (решение владельца 2026-10-05).
// Позиция прайса обязательна «Специалисту» (2.8b), подработке — по желанию. «Подтвердить
// телефон» с артборда — в v1: на старте — без лишних шагов для пользователя (решение владельца
// 2026-10-01).
import type {
  DistrictOut,
  ProfileOut,
  ProfileUpdateIn,
  ServiceOut,
  ServicesOut,
  WorkMode,
} from '@sosed/api-client';
import {
  getPricingListMyServicesQueryKey,
  pricingAddMyService,
  pricingChangeMyService,
  specialistsSetMyAreas,
  specialistsSubmitMyProfile,
  specialistsUpdateMyProfile,
} from '@sosed/api-client';
import { selectableDistricts, useCities, useDistricts, useMyServices } from '@sosed/hooks';
import { moneyValue, useFormat, useLocale, useTranslation } from '@sosed/i18n';
import { useBackButton, usePlatform } from '@sosed/platform';
import { Chip, Chips, Input, Segmented, Text } from '@sosed/ui-web';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useId, useRef, useState } from 'react';

import { LoadState } from '../shared/LoadState.tsx';
import { SaveError } from '../shared/SaveError.tsx';
import { WizardHeader } from '../shared/WizardHeader.tsx';
import { useChipList } from '../shared/chips.ts';
import { useBecomeFlow, useDraftProfile, useStepButton } from '../shared/flow.ts';
import { sameList, sameSet } from '../shared/same.ts';
import type { Radius } from '../shared/store.ts';
import { useBecomeStore } from '../shared/store.ts';
import { WholeCity } from '../shared/WholeCity.tsx';
import { MAX_AREAS, wholeCityAvailable, wholeCityDefault } from '../shared/wholeCity.ts';

/** Как на артборде: четыре района и «Ещё N районов». */
const VISIBLE_DISTRICTS = 4;
/** MAX_TITLE позиции прайса (backend pricing). */
const MAX_SERVICE_TITLE = 120;
const PARA_PER_DINAR = 100;
const RADII: readonly Radius[] = [3, 5, 10];
/** Радиус по умолчанию — как на артборде. */
const DEFAULT_RADIUS: Radius = 5;

type Format = 'at_client' | 'at_own_place' | 'both';
const FORMATS: readonly Format[] = ['at_client', 'at_own_place', 'both'];
const FORMAT_LABELS = { at_client: 'atClient', at_own_place: 'atOwnPlace', both: 'both' } as const;

/** Формат по режимам работы; не выбран — «Выезжаю», как на артборде. */
function formatOf(modes: readonly WorkMode[]): Format {
  const travels = modes.includes('at_client');
  const hosts = modes.includes('at_own_place');
  if (travels && hosts) return 'both';
  return hosts ? 'at_own_place' : 'at_client';
}

/** Режимы по формату. «Онлайн» мастер не спрашивает — он остаётся как был (правка — в S34). */
function modesOf(format: Format, current: readonly WorkMode[]): WorkMode[] {
  const modes: WorkMode[] = format === 'both' ? ['at_client', 'at_own_place'] : [format];
  return current.includes('remote') ? [...modes, 'remote'] : modes;
}

/** Цена позиции в динарах — для поля ввода. */
function dinars(service: ServiceOut | null): string {
  const amount = service?.price_min?.amount;
  return amount ? String(Math.round(amount / PARA_PER_DINAR)) : '';
}

export function AreaScreen() {
  const { t } = useTranslation('specialist');
  const locale = useLocale();
  const flow = useBecomeFlow();
  const { query, draft } = useDraftProfile();
  const districts = useDistricts(draft?.city_id ?? null, locale);
  const services = useMyServices({ enabled: draft !== undefined });
  const cities = useCities(locale);
  useBackButton(() => flow.back('about'));

  if (draft && districts.data && services.data && cities.data) {
    const city = cities.data.find((candidate) => candidate.id === draft.city_id);
    return (
      <AreaForm
        profile={draft}
        districts={selectableDistricts(districts.data, locale)}
        first={services.data.items[0] ?? null}
        city={city?.name ?? null}
      />
    );
  }
  const loads = [query, districts, services, cities];
  const failed = loads.find((load) => load.isError);
  return (
    <section className="flex flex-col gap-3 px-4 pt-3 pb-6">
      <WizardHeader step={3} title={t('become.area.title')} />
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

function AreaForm({
  profile,
  districts,
  first,
  city,
}: {
  profile: ProfileOut;
  districts: DistrictOut[];
  /** Первая позиция прайса, если уже есть: шаг её правит, а не добавляет вторую. */
  first: ServiceOut | null;
  city: string | null;
}) {
  const { t } = useTranslation('specialist');
  const { number } = useFormat();
  const locale = useLocale();
  const platform = usePlatform();
  const flow = useBecomeFlow();
  const queryClient = useQueryClient();
  const input = useBecomeStore();
  const districtsId = useId();
  const serviceId = useId();
  const serviceHintId = useId();
  // незаполненное подсвечиваем после первого нажатия «Отправить на проверку»
  const [checked, setChecked] = useState(false);
  // Idempotency-Key первой позиции: повтор после потерянного ответа не добавит вторую
  const key = useRef<string | null>(null);

  const modes = input.workModes ?? profile.work_modes;
  const format = formatOf(modes);
  const travels = format !== 'at_own_place';
  // «Весь город»: пока его не трогали — по профилю и формату (shared/wholeCity.ts)
  const whole =
    wholeCityAvailable(districts) &&
    (input.wholeCity ?? wholeCityDefault(districts, profile.district_ids, travels));
  const picked = input.districtIds ?? profile.district_ids;
  const districtIds = whole ? districts.map((district) => district.id) : picked;
  const radius =
    input.radius ?? RADII.find((km) => km === profile.travel_radius_km) ?? DEFAULT_RADIUS;
  const title = input.serviceTitle ?? first?.title ?? '';
  const price = input.servicePrice ?? dinars(first);
  // при «весь город» список свёрнут: раскроется — первыми те, что отмечены по отдельности
  const chips = useChipList(districts, whole ? [] : districtIds, VISIBLE_DISTRICTS);
  const pro = profile.kind === 'pro';
  // позиция прайса нужна «Специалисту», а подработке — если её начали заполнять
  const priced = pro || title.trim() !== '' || price !== '';
  const missing = {
    districts: travels && districtIds.length === 0,
    title: priced && title.trim() === '',
    price: priced && !(Number(price) > 0),
  };

  const saveFirstService = async () => {
    const service = { title: title.trim(), price_min: Number(price) * PARA_PER_DINAR };
    const listKey = getPricingListMyServicesQueryKey();
    if (!first) {
      key.current ??= crypto.randomUUID();
      const created = await pricingAddMyService(
        { ...service, price_type: 'fixed' },
        { 'Idempotency-Key': key.current },
      );
      // теперь она первая: повтор после ошибки отправки её правит, а не добавляет новую
      queryClient.setQueryData<ServicesOut>(listKey, { items: [created] });
    } else if (service.title !== first.title || price !== dinars(first)) {
      const changed = await pricingChangeMyService(first.id, service);
      queryClient.setQueryData<ServicesOut>(listKey, (list) =>
        list
          ? { items: list.items.map((item) => (item.id === changed.id ? changed : item)) }
          : list,
      );
    }
  };

  const submit = useMutation({
    mutationFn: async () => {
      if (!sameSet(districtIds, profile.district_ids)) {
        flow.saved(await specialistsSetMyAreas({ district_ids: districtIds }));
      }
      const patch: ProfileUpdateIn = {};
      const workModes = modes.length > 0 ? modes : modesOf(format, modes);
      if (!sameList(workModes, profile.work_modes)) patch.work_modes = workModes;
      if (travels && radius !== profile.travel_radius_km) patch.travel_radius_km = radius;
      if (Object.keys(patch).length > 0) flow.saved(await specialistsUpdateMyProfile(patch));
      if (priced) await saveFirstService();
      return specialistsSubmitMyProfile();
    },
    onSuccess: (submitted) => {
      platform.haptics.notification('success');
      flow.finish(submitted);
    },
  });

  const send = () => {
    if (submit.isPending) return;
    if (missing.districts || missing.title || missing.price) {
      setChecked(true);
      platform.haptics.notification('error');
      return;
    }
    submit.mutate();
  };
  useStepButton({ text: t('become.area.submit'), onClick: send, loading: submit.isPending });

  const toggleDistrict = (id: number) => {
    if (districtIds.includes(id)) {
      input.set({ districtIds: districtIds.filter((other) => other !== id) });
    } else if (districtIds.length >= MAX_AREAS) {
      platform.haptics.notification('warning');
      return;
    } else {
      input.set({ districtIds: [...districtIds, id] });
    }
    platform.haptics.selection();
  };
  const chooseWholeCity = (next: boolean) => {
    platform.haptics.selection();
    input.set({ wholeCity: next });
  };
  const chooseFormat = (next: Format) => {
    platform.haptics.selection();
    input.set({ workModes: modesOf(next, modes) });
  };
  const chooseRadius = (value: string) => {
    platform.haptics.selection();
    input.set({ radius: RADII.find((km) => String(km) === value) ?? DEFAULT_RADIUS });
  };
  const editService = (patch: { serviceTitle?: string; servicePrice?: string }) => {
    key.current = null;
    input.set(patch);
  };

  return (
    <section className="flex flex-col gap-3 px-4 pt-3 pb-6">
      <WizardHeader step={3} title={t('become.area.title')} />
      <section aria-labelledby={districtsId} className="flex flex-col gap-2">
        <h2 id={districtsId} className="m-0 text-sm font-semibold">
          {city ? t('become.area.districts', { city }) : t('become.area.districtsPlain')}
        </h2>
        {wholeCityAvailable(districts) && (
          <WholeCity city={city} checked={whole} onChange={chooseWholeCity} />
        )}
        {!whole && (
          <Chips wrap>
            {chips.visible.map((district) => {
              const on = districtIds.includes(district.id);
              return (
                <Chip
                  key={district.id}
                  selected={on}
                  icon={on ? 'check' : undefined}
                  onClick={() => toggleDistrict(district.id)}
                >
                  {district.name}
                </Chip>
              );
            })}
            {chips.hidden > 0 && (
              <Chip expanded={chips.expanded} onClick={chips.toggle}>
                {chips.expanded
                  ? t('become.area.lessDistricts')
                  : t('become.area.moreDistricts', { count: chips.hidden })}
              </Chip>
            )}
          </Chips>
        )}
        {checked && missing.districts && (
          <p role="alert" className="m-0 text-cap text-danger">
            {t('become.missing.area_ids')}
          </p>
        )}
      </section>
      <div className="flex flex-col gap-1.5">
        <span aria-hidden="true" className="text-sm font-semibold">
          {t('become.area.format')}
        </span>
        <Segmented
          label={t('become.area.format')}
          value={format}
          onChange={chooseFormat}
          options={FORMATS.map((value) => ({
            value,
            label: t(`become.area.${FORMAT_LABELS[value]}`),
          }))}
        />
      </div>
      {travels && (
        <div className="flex flex-col gap-1.5">
          <span aria-hidden="true" className="text-sm font-semibold">
            {t('become.area.radius')}
          </span>
          <Segmented
            label={t('become.area.radius')}
            value={String(radius)}
            onChange={chooseRadius}
            options={RADII.map((km) => ({
              value: String(km),
              label: t('become.area.radiusKm', { km }),
            }))}
          />
        </div>
      )}
      <div className="flex flex-col gap-1.5">
        <label htmlFor={serviceId} className="text-sm font-semibold">
          {t('become.area.price')}
        </label>
        {/* ширины — у обёрток: рамка Input сама растягивается на всю ширину (w-full) */}
        <div className="flex gap-2">
          <div className="min-w-0 flex-1">
            <Input
              id={serviceId}
              value={title}
              maxLength={MAX_SERVICE_TITLE}
              placeholder={t('become.area.priceTitlePlaceholder')}
              invalid={checked && missing.title}
              aria-describedby={serviceHintId}
              onChange={(event) => editService({ serviceTitle: event.target.value })}
            />
          </div>
          <div className="w-33 flex-none">
            <Input
              inputMode="numeric"
              // с разрядами, как на артборде («2 000»; в sr — «2.000»); хранятся только цифры
              value={price && number(Number(price))}
              suffix="RSD"
              aria-label={t('become.area.priceAmount')}
              invalid={checked && missing.price}
              aria-describedby={serviceHintId}
              onChange={(event) =>
                editService({
                  // «2.000,00» — 2 000, а не 200 000 (ADV-10)
                  servicePrice: String(moneyValue(event.target.value, locale) ?? ''),
                })
              }
            />
          </div>
        </div>
        {checked && missing.title && (
          <p role="alert" className="m-0 text-cap text-danger">
            {t('become.area.serviceTitleError')}
          </p>
        )}
        {checked && missing.price && (
          <p role="alert" className="m-0 text-cap text-danger">
            {t('become.area.servicePriceError')}
          </p>
        )}
        <p id={serviceHintId} className="m-0 text-cap text-text2">
          {pro ? t('become.area.priceHint') : t('become.area.priceOptional')}
        </p>
      </div>
      <Text variant="cap">{t('become.area.review')}</Text>
      {submit.isError && <SaveError error={submit.error} />}
    </section>
  );
}
