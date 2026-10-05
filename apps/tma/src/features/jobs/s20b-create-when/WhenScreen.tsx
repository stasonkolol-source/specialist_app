// S20b «Когда и где?», шаг 2 из 4 (DEVELOPMENT_PLAN 5.2): когда — срочно, сегодня (с удобным
// окном), в ближайшие дни или своя дата и время; где — район города (город — из профиля, иначе
// пилотный) на схеме: исполнители видят только область района, точный адрес — только выбранный, в
// карточке сделки. Район — из списка или «Определить по геолокации» (LocateDistrict): человек не
// обязан знать, как называется его район. «Указать на карте» (Q28) — точка на своей карте
// Нови-Сада (MapPicker), если карта включена (VITE_MAP_ASSETS_URL): в заявку и тогда уходит только
// район, точка нигде не хранится.
import type { DistrictOut } from '@sosed/api-client';
import { useIdentityGetMe } from '@sosed/api-client';
import {
  MAX_DAYS_AHEAD,
  TODAY_SLOTS,
  WHEN_CHOICES,
  addDays,
  businessDay,
  isSlotOpen,
  slotKey,
} from '@sosed/domain';
import type { JobDraft } from '@sosed/hooks';
import {
  JOB_ADDRESS_MAX,
  defaultCity,
  selectableDistricts,
  useCities,
  useDistricts,
  whenProblems,
} from '@sosed/hooks';
import { useLocale, useTranslation } from '@sosed/i18n';
import { usePlatform } from '@sosed/platform';
import {
  Chip,
  Chips,
  Field,
  Icon,
  Input,
  MapPreview,
  Option,
  PickerButton,
  Row,
  Sheet,
  Text,
} from '@sosed/ui-web';
import { useEffect, useId, useState } from 'react';

import { useJobDraft } from '../shared/draft.ts';
import { useCreateFlow, useStepButton } from '../shared/flow.ts';
import { WizardSkeleton } from '../shared/skeletons.tsx';
import { WizardHeader } from '../shared/WizardHeader.tsx';
import type { LocateStatus } from './LocateDistrict.tsx';
import { LocateDistrict } from './LocateDistrict.tsx';
import type { MapPick } from './map/config.ts';
import { MAP_CITY_SLUG, mapAssetsBase } from './map/config.ts';
import { MapPickerHost } from './map/MapPickerHost.tsx';

/** Карта открывается на районе крупнее, чем на городе: район виден целиком с улицами. */
const DISTRICT_ZOOM = 14;
const CITY_ZOOM = 12;

export function WhenScreen() {
  const { draft, patch } = useJobDraft();
  const flow = useCreateFlow('when', draft);
  if (!draft) return <WizardSkeleton step={2} />;
  return <WhenForm draft={draft} patch={patch} next={flow.next} />;
}

function WhenForm({
  draft,
  patch,
  next,
}: {
  draft: JobDraft;
  patch: (patch: Partial<JobDraft>) => void;
  next: () => void;
}) {
  const { t } = useTranslation('jobs');
  const { t: common } = useTranslation();
  const locale = useLocale();
  const platform = usePlatform();
  const now = new Date();
  const [checked, setChecked] = useState(false);
  const [picking, setPicking] = useState(false);
  const [located, setLocated] = useState<LocateStatus>({ kind: 'idle' });
  const [mapping, setMapping] = useState(false);
  const [mapPick, setMapPick] = useState<MapPick | null>(null);
  const city = useJobCity(draft, patch);
  const districts = selectableDistricts(useDistricts(city?.id ?? null, locale).data ?? [], locale);
  const district = districts.find((item) => item.id === draft.districtId) ?? null;
  const problems = whenProblems(draft, now);
  const whenId = useId();
  const mapBase = city?.slug === MAP_CITY_SLUG ? mapAssetsBase() : null;

  const closeMap = () => {
    setMapping(false);
    setMapPick(null);
  };
  const chooseOnMap = (pick: MapPick) => {
    platform.haptics.selection();
    patch({ districtId: pick.district.id });
    setLocated({ kind: 'found', districtId: pick.district.id });
    closeMap();
  };

  // MainButton у шага одна: пока открыта карта, она — «Выбрать» точки под меткой
  useStepButton(
    mapping
      ? {
          text: t('create.when.map.choose'),
          enabled: mapPick !== null,
          onClick: () => {
            if (mapPick) chooseOnMap(mapPick);
          },
        }
      : {
          text: common('action.next'),
          onClick: () => {
            setChecked(true);
            if (problems.length === 0) next();
          },
        },
  );

  return (
    <section className="flex flex-col gap-4 px-4 pt-3 pb-6">
      <WizardHeader step={2} title={t('create.when.title')} />
      <div className="flex flex-col gap-2" role="radiogroup" aria-labelledby={whenId}>
        <span id={whenId} className="text-sm font-semibold">
          {t('create.when.when')}
        </span>
        <div className="grid grid-cols-2 gap-2">
          {WHEN_CHOICES.map((choice) => (
            <Option
              key={choice}
              control="none"
              title={t(`create.when.${choice}`)}
              description={t(`create.when.${choice}Hint`)}
              checked={draft.when === choice}
              onChange={() => patch({ when: choice })}
            />
          ))}
        </div>
        {checked && problems.includes('when') && (
          <Text variant="cap" className="text-danger">
            {t('create.when.missingWhen')}
          </Text>
        )}
      </div>
      {draft.when === 'today' && <TodaySlots draft={draft} patch={patch} now={now} />}
      {draft.when === 'date' && (
        <DateTime
          draft={draft}
          patch={patch}
          now={now}
          error={checked && problems.includes('date') ? t('create.when.missingDate') : undefined}
        />
      )}
      <div className="flex flex-col">
        <Field
          label={t('create.when.where')}
          error={
            checked && problems.includes('district') ? t('create.when.missingDistrict') : undefined
          }
        >
          <PickerButton icon="pin" onClick={() => setPicking(true)}>
            {district && city
              ? `${city.name}, ${district.name}`
              : (city?.name ?? t('create.when.districtPick'))}
          </PickerButton>
        </Field>
        {city && districts.length > 0 && (
          <LocateDistrict
            cityId={city.id}
            districts={districts}
            selected={draft.districtId}
            status={located}
            onStatus={setLocated}
            onFound={(item) => patch({ districtId: item.id })}
            onOpenMap={mapBase ? () => setMapping(true) : undefined}
          />
        )}
      </div>
      {district && (
        <MapPreview
          label={district.name}
          caption={t('create.when.area')}
          description={`${t('create.when.area')}: ${district.name}`}
        />
      )}
      <Field label={t('create.when.address')} hint={t('create.when.addressHint')}>
        <Input
          icon="lock"
          value={draft.address}
          maxLength={JOB_ADDRESS_MAX}
          placeholder={t('create.when.addressPlaceholder')}
          autoComplete="street-address"
          onChange={(event) => patch({ address: event.target.value })}
        />
      </Field>
      {mapping && city && mapBase && (
        <MapPickerHost
          base={mapBase}
          cityId={city.id}
          districts={districts}
          start={
            district
              ? { point: district.center, zoom: DISTRICT_ZOOM }
              : { point: city.center, zoom: CITY_ZOOM }
          }
          onPickChange={setMapPick}
          onCancel={closeMap}
          onUnavailable={() => {
            closeMap();
            setLocated({ kind: 'mapFailed' });
          }}
        />
      )}
      <DistrictPicker
        open={picking}
        districts={districts}
        selected={draft.districtId}
        onClose={() => setPicking(false)}
        onChoose={(item) => {
          patch({ districtId: item.id });
          setPicking(false);
        }}
      />
    </section>
  );
}

/** Город заявки: свой (home_city_id) или первый открытый; запоминается в черновике. */
function useJobCity(draft: JobDraft, patch: (patch: Partial<JobDraft>) => void) {
  const locale = useLocale();
  const platform = usePlatform();
  const inTelegram = platform.launch.rawInitData !== null;
  const me = useIdentityGetMe({ query: { enabled: inTelegram } });
  const cities = useCities(locale).data;
  const ready = cities !== undefined && !(inTelegram && me.isPending);
  const id = ready ? (draft.cityId ?? defaultCity(cities, me.data?.home_city_id ?? null)) : null;
  useEffect(() => {
    if (id !== null && draft.cityId !== id) patch({ cityId: id, districtId: null });
  }, [id, draft.cityId, patch]);
  return cities?.find((city) => city.id === id) ?? null;
}

function TodaySlots({
  draft,
  patch,
  now,
}: {
  draft: JobDraft;
  patch: (patch: Partial<JobDraft>) => void;
  now: Date;
}) {
  const { t } = useTranslation('jobs');
  return (
    <div className="flex flex-col gap-2">
      <span className="text-sm font-semibold">{t('create.when.slots')}</span>
      <Chips label={t('create.when.slots')} wrap>
        {TODAY_SLOTS.map((slot) => {
          const key = slotKey(slot);
          const selected = draft.slot === key;
          return (
            <Chip
              key={key}
              selected={selected}
              disabled={!isSlotOpen(slot, now)}
              onClick={() => patch({ slot: selected ? null : key })}
            >
              {`${slot[0]}–${slot[1]}`}
            </Chip>
          );
        })}
      </Chips>
    </div>
  );
}

function DateTime({
  draft,
  patch,
  now,
  error,
}: {
  draft: JobDraft;
  patch: (patch: Partial<JobDraft>) => void;
  now: Date;
  error?: string;
}) {
  const { t } = useTranslation('jobs');
  const today = businessDay(now);
  return (
    <div className="grid grid-cols-2 gap-2">
      <Field label={t('create.when.day')} error={error}>
        <Input
          type="date"
          value={draft.day ?? ''}
          min={today}
          max={addDays(today, MAX_DAYS_AHEAD)}
          onChange={(event) => patch({ day: event.target.value || null })}
        />
      </Field>
      <Field label={t('create.when.time')}>
        <Input
          type="time"
          step={900}
          value={draft.time ?? ''}
          onChange={(event) => patch({ time: event.target.value || null })}
        />
      </Field>
    </div>
  );
}

function DistrictPicker({
  open,
  districts,
  selected,
  onClose,
  onChoose,
}: {
  open: boolean;
  districts: readonly DistrictOut[];
  selected: number | null;
  onClose: () => void;
  onChoose: (district: DistrictOut) => void;
}) {
  const { t } = useTranslation('jobs');
  const { t: common } = useTranslation();
  return (
    <Sheet
      open={open}
      title={t('create.when.district')}
      onClose={onClose}
      closeLabel={common('action.close')}
    >
      <div className="-mx-4 flex flex-col">
        {districts.map((district) => (
          <Row
            key={district.id}
            title={district.name}
            trailing={
              district.id === selected ? <Icon name="check" className="text-accent" /> : undefined
            }
            onClick={() => onChoose(district)}
          />
        ))}
      </div>
    </Sheet>
  );
}
