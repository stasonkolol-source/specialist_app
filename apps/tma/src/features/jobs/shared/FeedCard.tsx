// Карточка заявки в ленте S13 и в сохранённых S12: строки для `JobCard` — бюджет, «когда» и
// категория бейджами, «5 мин назад», район с расстоянием и счётчик мест; нажатие ведёт в заявку
// S15 (с точкой ленты — для «≈ 1,2 км от вас»).
import type { JobCardOut } from '@sosed/api-client';
import { useFormat, useTranslation } from '@sosed/i18n';
import type { JobCardBadge } from '@sosed/ui-web';
import { JobCard } from '@sosed/ui-web';
import { useRouter } from '@tanstack/react-router';

import { useBudgetText, usePlaceText, useSlots, useWhenBadge } from './labels.ts';
import type { JobSearch } from './paths.ts';
import { JOBS_PATHS } from './paths.ts';

export function FeedCard({
  card,
  category,
  district,
  point,
}: {
  card: JobCardOut;
  /** Название категории из справочника; нет в дереве — без бейджа. */
  category: string | null;
  district: string | null;
  point: JobSearch;
}) {
  const { t } = useTranslation('jobs');
  const format = useFormat();
  const router = useRouter();
  const whenBadge = useWhenBadge();
  const budgetText = useBudgetText();
  const placeText = usePlaceText();
  const slots = useSlots();
  const budget = budgetText(card);
  const badges: JobCardBadge[] = [whenBadge(card)];
  if (category) badges.push({ label: category, tone: 'mute' });
  const location = { to: JOBS_PATHS.job, params: { jobId: card.id }, search: point } as const;
  return (
    <JobCard
      title={card.title}
      budget={budget ?? t('card.negotiable')}
      negotiable={budget === null}
      badges={badges}
      time={format.relative(new Date(card.published_at))}
      description={card.description}
      photos={card.photos.map((photo) => ({ src: photo.url, placeholder: photo.placeholder }))}
      photoLabel={(number) => t('card.photo', { number })}
      place={placeText(district, card.distance_m) || null}
      slots={slots(card)}
      href={router.history.createHref(router.buildLocation(location).href)}
      onOpen={(event) => {
        event.preventDefault();
        void router.navigate(location);
      }}
    />
  );
}
