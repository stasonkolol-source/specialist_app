// Сегменты вкладки «Заявки» (nav.seg на S13, S17, S22): «Лента / Мои отклики / Мои заявки» —
// ссылки на свои адреса. Переход заменяет запись в истории: «Назад» уводит с вкладки, а не по
// сегментам.
import { useTranslation } from '@sosed/i18n';
import { SegmentedNav } from '@sosed/ui-web';
import { useRouter } from '@tanstack/react-router';

import type { JobsSegment } from './paths.ts';
import { JOBS_PATHS, JOBS_SEGMENTS } from './paths.ts';

export function JobsSegments({ current }: { current: JobsSegment }) {
  const { t } = useTranslation('jobs');
  const router = useRouter();
  return (
    <SegmentedNav
      label={t('segments.label')}
      current={current}
      items={JOBS_SEGMENTS.map((segment) => ({
        id: segment,
        label: t(`segments.${segment}`),
        href: router.history.createHref(JOBS_PATHS[segment]),
      }))}
      onNavigate={(id, event) => {
        event.preventDefault();
        const segment = JOBS_SEGMENTS.find((item) => item === id);
        if (segment && segment !== current) {
          void router.navigate({ to: JOBS_PATHS[segment], replace: true });
        }
      }}
    />
  );
}
