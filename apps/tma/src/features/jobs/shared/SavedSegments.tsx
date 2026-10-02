// Сегменты избранного S12: «Мастера · 3» (фича catalog) и «Задачи · 2» (сохранённые заявки) —
// ссылки на свои адреса; числа — из тех же списков, что сердечки. Переход заменяет запись в
// истории: «Назад» уводит из избранного, а не по сегментам.
import { favoriteIds, savedJobIds, useFavorites, useSavedJobs } from '@sosed/hooks';
import { useLocale, useTranslation } from '@sosed/i18n';
import { SegmentedNav } from '@sosed/ui-web';
import { useRouter } from '@tanstack/react-router';

import type { SavedSegment } from './paths.ts';
import { SAVED_PATHS } from './paths.ts';

export function SavedSegments({ current }: { current: SavedSegment }) {
  const { t } = useTranslation('jobs');
  const router = useRouter();
  const masters = useFavorites(useLocale()).data;
  const jobs = useSavedJobs().data;
  const label = (text: string, count: number | undefined) =>
    count === undefined ? text : t('saved.withCount', { label: text, count });
  const items = [
    {
      id: 'masters',
      label: label(t('saved.masters'), masters && favoriteIds(masters).size),
      href: router.history.createHref(SAVED_PATHS.masters),
    },
    {
      id: 'jobs',
      label: label(t('saved.jobs'), jobs && savedJobIds(jobs).size),
      href: router.history.createHref(SAVED_PATHS.jobs),
    },
  ] as const;
  return (
    <SegmentedNav
      label={t('saved.segments')}
      current={current}
      items={items}
      onNavigate={(id, event) => {
        event.preventDefault();
        if (id !== current && (id === 'masters' || id === 'jobs')) {
          void router.navigate({ to: SAVED_PATHS[id], replace: true });
        }
      }}
    />
  );
}
