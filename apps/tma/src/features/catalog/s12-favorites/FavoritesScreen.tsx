// S12 Избранное (DEVELOPMENT_PLAN 4.6): «мои мастера» — карточки, как в выдаче, новые первыми;
// сердечко убирает из списка сразу. Пусто — подсказка и «Найти специалиста». Вход — из профиля
// S31; гостю избранного нет — «Откройте в Telegram». Сегмент «Задачи» — сохранённые заявки (фича
// jobs, 5.3).
import type { SpecialistCardOut } from '@sosed/api-client';
import { getSession } from '@sosed/api-client';
import { useTranslation } from '@sosed/i18n';
import { useBackButton } from '@sosed/platform';
import { Banner, Button, EmptyState, Heading, SpecialistCardSkeleton } from '@sosed/ui-web';
import { useRouter } from '@tanstack/react-router';

import { FavoritesSegments } from '../shared/FavoritesSegments.tsx';
import { LoadError } from '../shared/LoadError.tsx';
import { ResultCard } from '../shared/ResultCard.tsx';
import { useFavoriteToggle } from '../shared/favorite.ts';
import { CATALOG_PATHS } from '../shared/paths.ts';

/** Профиль S31 (features/account): фичи не импортируют друг друга. */
const ACCOUNT_PATH = '/profile';
const SKELETON_CARDS = 2;

export function FavoritesScreen() {
  const { t } = useTranslation('catalog');
  const common = useTranslation().t;
  const router = useRouter();
  const { control, failure, favorites } = useFavoriteToggle();
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
  } else if (favorites.data) {
    const items: SpecialistCardOut[] = favorites.data.items;
    content =
      items.length === 0 ? (
        <EmptyState
          as="h2"
          icon="heart"
          title={t('favorites.emptyTitle')}
          action={
            <Button
              variant="secondary"
              onClick={() => void router.navigate({ to: CATALOG_PATHS.categories })}
            >
              {t('favorites.find')}
            </Button>
          }
        >
          {t('favorites.emptyText')}
        </EmptyState>
      ) : (
        <div className="flex flex-col gap-3">
          {items.map((card) => (
            <ResultCard key={card.profile_id} card={card} favorite={control(card)} />
          ))}
        </div>
      );
  } else if (favorites.isError) {
    content = (
      <LoadError
        error={favorites.error}
        onRetry={() => void favorites.refetch()}
        retrying={favorites.isRefetching}
      />
    );
  } else {
    content = (
      <div className="flex flex-col gap-3" aria-busy="true">
        {Array.from({ length: SKELETON_CARDS }, (_, card) => (
          <SpecialistCardSkeleton key={card} />
        ))}
      </div>
    );
  }
  return (
    <section className="flex flex-col gap-3 px-4 pt-3 pb-6">
      <Heading variant="h2" as="h1">
        {t('favorites.title')}
      </Heading>
      <FavoritesSegments current="masters" />
      {failure && (
        <Banner tone="danger" role="alert">
          {failure}
        </Banner>
      )}
      {content}
    </section>
  );
}
