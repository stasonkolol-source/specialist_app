// Карточка специалиста из выдачи S05 и избранного S12 (DEVELOPMENT_PLAN 4.4, 4.6): строки для
// `SpecialistCard` — рейтинг, район с расстоянием, языки, «Сегодня до …», «Телефон подтверждён»,
// цена «от»; нажатие ведёт в профиль S08, сердечко — в избранное.
import type { SpecialistCardOut } from '@sosed/api-client';
import { useFormat, useTranslation } from '@sosed/i18n';
import type { SpecialistBadge } from '@sosed/ui-web';
import { SpecialistCard } from '@sosed/ui-web';
import { useRouter } from '@tanstack/react-router';

import type { FavoriteControl } from './favorite.ts';
import { CARD_PATHS, profilePath } from './paths.ts';

const PHONE_VERIFIED = 'phone_verified';

export function ResultCard({
  card,
  favorite,
}: {
  card: SpecialistCardOut;
  favorite?: FavoriteControl;
}) {
  const { t } = useTranslation('catalog');
  const common = useTranslation().t;
  const format = useFormat();
  const router = useRouter();
  const now = new Date();
  const place = [
    card.district?.name,
    card.distance_m === null ? undefined : format.distance(card.distance_m),
  ]
    .filter(Boolean)
    .join(', ');
  const meta = [place, card.languages.join(', ')].filter(Boolean);
  const until = card.available_until ? new Date(card.available_until) : null;
  const badges: SpecialistBadge[] = [];
  if (until && until > now) {
    badges.push({
      label: t('results.todayUntil', { time: format.time(until) }),
      tone: 'ok',
      dot: true,
    });
  }
  if (card.badges.includes(PHONE_VERIFIED)) {
    badges.push({ label: t('results.phoneVerified'), tone: 'info', icon: 'shield' });
  }
  const price =
    card.price_from !== null
      ? format.price({ type: 'from', min: card.price_from })
      : card.negotiable
        ? common('price.negotiable')
        : null;
  return (
    <SpecialistCard
      name={card.display_name}
      headline={card.headline}
      photo={card.avatar ? { src: card.avatar.url, placeholder: card.avatar.placeholder } : null}
      rating={card.rating === null || card.is_new ? null : format.rating(card.rating)}
      reviews={t('results.reviews', { count: card.rating_count })}
      newLabel={common('rating.new')}
      meta={meta}
      badges={badges}
      price={price}
      href={router.history.createHref(profilePath(card.profile_id))}
      onOpen={(event) => {
        event.preventDefault();
        void router.navigate({ to: CARD_PATHS.profile, params: { profileId: card.profile_id } });
      }}
      favorite={favorite}
    />
  );
}
