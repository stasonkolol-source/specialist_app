// «Определить по геолокации» и «Указать на карте» под полем «Где» S20b: точка устройства (Telegram
// LocationManager, в браузере — geolocation) или точка на карте (MapPicker, Q28) → район города на
// backend (GET /geo/districts/locate, по границам районов) → район выбран. Человеку не нужно знать,
// как называется его район. Отказ, нет геолокации или точка за городом — спокойная подсказка выбрать
// из списка; список работает, как раньше. Итог общий для обоих путей — его держит WhenForm: карту
// открывает и закрывает он же (у него MainButton).
import type { DistrictOut } from '@sosed/api-client';
import { geoLocateDistrict } from '@sosed/api-client';
import { useTranslation } from '@sosed/i18n';
import { usePlatform } from '@sosed/platform';
import { Icon, LinkButton, cx } from '@sosed/ui-web';

import { useLocate } from '../shared/location.ts';

export type LocateStatus =
  { kind: 'idle' | 'busy' | 'failed' | 'mapFailed' } | { kind: 'found'; districtId: number };

export function LocateDistrict({
  cityId,
  districts,
  selected,
  status,
  onStatus,
  onFound,
  onOpenMap,
}: {
  cityId: number;
  /** Районы списка: определённый район выбирается из них, по id. */
  districts: readonly DistrictOut[];
  /** Выбранный район: «Район определён» — пока выбран тот, что определили. */
  selected: number | null;
  status: LocateStatus;
  onStatus: (status: LocateStatus) => void;
  onFound: (district: DistrictOut) => void;
  /** «Указать на карте»; без карты (VITE_MAP_ASSETS_URL пуст, другой город) — кнопки нет. */
  onOpenMap?: (() => void) | undefined;
}) {
  const { t } = useTranslation('jobs');
  const platform = usePlatform();
  const locate = useLocate();
  const busy = status.kind === 'busy';

  const run = async () => {
    onStatus({ kind: 'busy' });
    const point = await locate();
    const found = point
      ? await geoLocateDistrict({ city_id: cityId, ...point }).catch(() => null)
      : null;
    const district = found ? districts.find((item) => item.id === found.id) : undefined;
    if (!district) {
      platform.haptics.notification('warning');
      onStatus({ kind: 'failed' });
      return;
    }
    platform.haptics.selection();
    onFound(district);
    onStatus({ kind: 'found', districtId: district.id });
  };

  const located =
    status.kind === 'found' && status.districtId === selected
      ? districts.find((item) => item.id === selected)
      : undefined;
  return (
    <div className="flex flex-col items-start">
      <div className="-ml-2 flex flex-wrap items-center gap-x-2">
        <LinkButton
          disabled={busy}
          aria-busy={busy || undefined}
          onClick={() => void run()}
          className="gap-1.5"
        >
          <Icon name="locate" size={16} className={cx(busy && 'motion-safe:animate-pulse')} />
          {busy ? t('create.when.locating') : t('create.when.locate')}
        </LinkButton>
        {onOpenMap && (
          <LinkButton disabled={busy} onClick={onOpenMap} className="gap-1.5">
            <Icon name="map" size={16} />
            {t('create.when.mapOpen')}
          </LinkButton>
        )}
      </div>
      {/* итог — вежливо для скринридера, фокус остаётся на кнопке; область в DOM всегда, иначе
          первое сообщение не прочитают */}
      <p role="status" className="m-0 text-cap text-text2">
        {located
          ? t('create.when.located', { district: located.name })
          : status.kind === 'failed'
            ? t('create.when.locateFailed')
            : status.kind === 'mapFailed'
              ? t('create.when.map.unavailable')
              : ''}
      </p>
    </div>
  );
}
