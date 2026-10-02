// Сегменты избранного S12: «Мастера · 3» (здесь) и «Задачи · 2» (сохранённые заявки, фича jobs,
// 5.3) — ссылки на свои адреса; числа — из тех же списков, что сердечки. Переход заменяет запись
// в истории: «Назад» уводит из избранного, а не по сегментам.
import { favoriteIds, savedJobIds, useFavorites, useSavedJobs } from '@sosed/hooks';
import { useLocale, useTranslation } from '@sosed/i18n';
import { SegmentedNav } from '@sosed/ui-web';
import { useRouter } from '@tanstack/react-router';

import { FAVORITES_PATH, SAVED_JOBS_PATH } from './paths.ts';

const SEGMENTS = { masters: FAVORITES_PATH, jobs: SAVED_JOBS_PATH } as const;

export function FavoritesSegments({ current }: { current: keyof typeof SEGMENTS }) {
  const { t } = useTranslation('catalog');
  const router = useRouter();
  const masters = useFavorites(useLocale()).data;
  const jobs = useSavedJobs().data;
  const label = (text: string, count: number | undefined) =>
    count === undefined ? text : t('favorites.withCount', { label: text, count });
  return (
    <SegmentedNav
      label={t('favorites.segments')}
      current={current}
      items={[
        {
          id: 'masters',
          label: label(t('favorites.masters'), masters && favoriteIds(masters).size),
          href: router.history.createHref(SEGMENTS.masters),
        },
        {
          id: 'jobs',
          label: label(t('favorites.jobs'), jobs && savedJobIds(jobs).size),
          href: router.history.createHref(SEGMENTS.jobs),
        },
      ]}
      onNavigate={(id, event) => {
        event.preventDefault();
        if (id !== current && (id === 'masters' || id === 'jobs')) {
          void router.navigate({ to: SEGMENTS[id], replace: true });
        }
      }}
    />
  );
}
