// «Определить по геолокации» под полем «Где» S20b: точка устройства (Telegram LocationManager, в
// браузере — geolocation) → район города на backend (GET /geo/districts/locate, по границам районов)
// → район выбран. Человеку не нужно знать, как называется его район. Отказ, нет геолокации или
// точка за городом — спокойная подсказка выбрать из списка; список работает, как раньше.
import type { DistrictOut } from '@sosed/api-client';
import { geoLocateDistrict } from '@sosed/api-client';
import { useTranslation } from '@sosed/i18n';
import { usePlatform } from '@sosed/platform';
import { Icon, LinkButton, cx } from '@sosed/ui-web';
import { useState } from 'react';

import { useLocate } from '../shared/location.ts';

type Status = { kind: 'idle' | 'busy' | 'failed' } | { kind: 'found'; districtId: number };

export function LocateDistrict({
  cityId,
  districts,
  selected,
  onFound,
}: {
  cityId: number;
  /** Районы списка: определённый район выбирается из них, по id. */
  districts: readonly DistrictOut[];
  /** Выбранный район: «Район определён» — пока выбран тот, что определили. */
  selected: number | null;
  onFound: (district: DistrictOut) => void;
}) {
  const { t } = useTranslation('jobs');
  const platform = usePlatform();
  const locate = useLocate();
  const [status, setStatus] = useState<Status>({ kind: 'idle' });
  const busy = status.kind === 'busy';

  const run = async () => {
    setStatus({ kind: 'busy' });
    const point = await locate();
    const found = point
      ? await geoLocateDistrict({ city_id: cityId, ...point }).catch(() => null)
      : null;
    const district = found ? districts.find((item) => item.id === found.id) : undefined;
    if (!district) {
      platform.haptics.notification('warning');
      setStatus({ kind: 'failed' });
      return;
    }
    platform.haptics.selection();
    onFound(district);
    setStatus({ kind: 'found', districtId: district.id });
  };

  const located =
    status.kind === 'found' && status.districtId === selected
      ? districts.find((item) => item.id === selected)
      : undefined;
  return (
    <div className="flex flex-col items-start">
      <LinkButton
        disabled={busy}
        aria-busy={busy || undefined}
        onClick={() => void run()}
        className="-ml-2 gap-1.5"
      >
        <Icon name="locate" size={16} className={cx(busy && 'motion-safe:animate-pulse')} />
        {busy ? t('create.when.locating') : t('create.when.locate')}
      </LinkButton>
      {/* итог — вежливо для скринридера, фокус остаётся на кнопке; область в DOM всегда, иначе
          первое сообщение не прочитают */}
      <p role="status" className="m-0 text-cap text-text2">
        {located
          ? t('create.when.located', { district: located.name })
          : status.kind === 'failed'
            ? t('create.when.locateFailed')
            : ''}
      </p>
    </div>
  );
}
