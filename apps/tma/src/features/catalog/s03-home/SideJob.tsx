// «Ищете подработку? 6 новых задач рядом» на S03 (DEVELOPMENT_PLAN 5.3) — в ленту заявок S13:
// заявки города за сутки; без новых заявок блока нет. Своим чанком: счётчик и API заявок не нужны
// до первого кадра Главной (бюджет первого экрана 200 KB gzip).
import { useJobsCount } from '@sosed/hooks';
import { useTranslation } from '@sosed/i18n';
import { Card, Icon, RowIcon, Text } from '@sosed/ui-web';
import type { MouseEvent } from 'react';

/** «Новых» — опубликованных за сутки. */
const NEW_JOBS_HOURS = 24;

export function SideJob({
  cityId,
  href,
  onOpen,
}: {
  cityId: number;
  href: string;
  onOpen: (event: MouseEvent<HTMLElement>) => void;
}) {
  const { t } = useTranslation('catalog');
  const fresh = useJobsCount({ city_id: cityId }, NEW_JOBS_HOURS).data?.count ?? 0;
  if (fresh === 0) return null;
  return (
    <Card href={href} onClick={onOpen}>
      <span className="flex items-center gap-3">
        <RowIcon icon="briefcase" palette={3} xl />
        <span className="flex min-w-0 grow flex-col gap-1">
          <span className="font-semibold">{t('home.sideJobTitle')}</span>
          <Text as="span" variant="cap">
            {t('home.sideJobText', { count: fresh })}
          </Text>
        </span>
        <Icon name="chev-right" className="shrink-0 text-text2" />
      </span>
    </Card>
  );
}
