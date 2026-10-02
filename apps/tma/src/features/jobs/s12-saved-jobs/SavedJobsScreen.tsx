// S12 Избранное, сегмент «Задачи» (DEVELOPMENT_PLAN 5.3): сохранённые заявки карточками ленты,
// новые сохранения первыми; закрытые и истёкшие сервер не отдаёт. Убрать — сердечком на S15.
// Пусто — подсказка и «К ленте заявок». Вход — сегментом с «Мастеров» S12 (профиль S31); гостю
// избранного нет — «Откройте в Telegram».
import { getSession } from '@sosed/api-client';
import { selectableDistricts, useCategories, useDistricts, useSavedJobs } from '@sosed/hooks';
import { useLocale, useTranslation } from '@sosed/i18n';
import { useBackButton } from '@sosed/platform';
import { Button, EmptyState, Heading, Skeleton } from '@sosed/ui-web';
import { useRouter } from '@tanstack/react-router';

import { FeedCard } from '../shared/FeedCard.tsx';
import { LoadError } from '../shared/LoadError.tsx';
import { SavedSegments } from '../shared/SavedSegments.tsx';
import { findCategory } from '../shared/categories.ts';
import { useFeedCity } from '../shared/city.ts';
import { ACCOUNT_PATH, JOBS_PATHS } from '../shared/paths.ts';

const SKELETON_CARDS = 2;

export function SavedJobsScreen() {
  const { t } = useTranslation('jobs');
  const { t: common } = useTranslation();
  const locale = useLocale();
  const router = useRouter();
  const saved = useSavedJobs();
  const city = useFeedCity();
  const tree = useCategories(locale).data ?? [];
  const districts = selectableDistricts(useDistricts(city?.id ?? null, locale).data ?? [], locale);
  useBackButton(() => {
    if (router.history.canGoBack()) router.history.back();
    else void router.navigate({ to: ACCOUNT_PATH, replace: true });
  });

  let content;
  if (getSession() === null) {
    content = (
      <EmptyState as="h2" icon="lock" tone="neutral" title={common('profile.signedOutTitle')}>
        {common('profile.signedOutText')}
      </EmptyState>
    );
  } else if (saved.data) {
    content =
      saved.data.items.length === 0 ? (
        <EmptyState
          as="h2"
          icon="heart"
          title={t('saved.emptyTitle')}
          action={
            <Button
              variant="secondary"
              onClick={() => void router.navigate({ to: JOBS_PATHS.feed })}
            >
              {t('job.toFeed')}
            </Button>
          }
        >
          {t('saved.emptyText')}
        </EmptyState>
      ) : (
        <div className="flex flex-col gap-2.5">
          {saved.data.items.map((card) => (
            <FeedCard
              key={card.id}
              card={card}
              category={findCategory(tree, card.category_id)?.name ?? null}
              district={districts.find((item) => item.id === card.district_id)?.name ?? null}
              point={{}}
            />
          ))}
        </div>
      );
  } else if (saved.isError) {
    content = (
      <LoadError
        error={saved.error}
        onRetry={() => void saved.refetch()}
        retrying={saved.isRefetching}
      />
    );
  } else {
    content = (
      <div className="flex flex-col gap-2.5" aria-busy="true">
        {Array.from({ length: SKELETON_CARDS }, (_, card) => (
          <Skeleton key={card} radius="card" className="h-36 w-full" />
        ))}
      </div>
    );
  }

  return (
    <section className="flex flex-col gap-3 px-4 pt-3 pb-6">
      <Heading variant="h2" as="h1">
        {t('saved.title')}
      </Heading>
      <SavedSegments current="jobs" />
      {content}
    </section>
  );
}
