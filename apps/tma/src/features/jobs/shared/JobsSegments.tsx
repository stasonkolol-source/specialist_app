// Сегменты вкладки «Заявки» (nav.seg на S13, S17, S22): «Лента / Мои отклики / Мои заявки» —
// ссылки на свои адреса. Переход заменяет запись в истории: «Назад» уводит с вкладки, а не по
// сегментам. Новые отклики на свои заявки — красной точкой, цветом счётчика вкладки «Заявки» в
// таббаре, и на «Мои заявки»: видно, куда ведёт бейдж (вкладка сама открывает «Ленту»).
import { useBadges } from '@sosed/hooks';
import { useTranslation } from '@sosed/i18n';
import { SegmentedNav } from '@sosed/ui-web';
import { useRouter } from '@tanstack/react-router';

import type { JobsSegment } from './paths.ts';
import { JOBS_PATHS, JOBS_SEGMENTS } from './paths.ts';

export function JobsSegments({ current }: { current: JobsSegment }) {
  const { t } = useTranslation('jobs');
  const router = useRouter();
  const fresh = useBadges().data?.jobs ?? 0;
  return (
    <SegmentedNav
      label={t('segments.label')}
      current={current}
      items={JOBS_SEGMENTS.map((segment) => ({
        id: segment,
        label:
          segment === 'mine' && fresh > 0 ? (
            <>
              {t(`segments.${segment}`)}
              <Fresh count={fresh} />
            </>
          ) : (
            t(`segments.${segment}`)
          ),
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

/** Новые отклики: точка цвета счётчика таббара — число в сегменте на 360 px упиралось бы в его
 *  край (сам счётчик — на вкладке); скринридер слышит «Мои заявки, 2 новых отклика». */
function Fresh({ count }: { count: number }) {
  const { t } = useTranslation();
  return (
    <>
      <span aria-hidden="true" className="size-2 shrink-0 rounded-full bg-urgent" />
      <span className="sr-only">{`, ${t('nav.count.jobs', { count })}`}</span>
    </>
  );
}
