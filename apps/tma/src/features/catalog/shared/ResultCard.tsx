// Карточка специалиста из выдачи S05, избранного S12 и «Свободны сегодня рядом» на Главной S03
// (DEVELOPMENT_PLAN 4.4, 4.6, 4.8): строки для `SpecialistCard` — бейдж «Подработка», рейтинг,
// район с расстоянием, языки словами («рус., серб.»: код «uk» читается как «Великобритания»),
// «Сегодня до …», «Телефон подтверждён», цена «от»; нажатие ведёт в профиль S08, сердечко — в
// избранное.
import type { SpecialistCardOut } from '@sosed/api-client';
import { SERVICE_UNITS } from '@sosed/domain';
import { useFormat, useTranslation } from '@sosed/i18n';
import type { SpecialistBadge } from '@sosed/ui-web';
import { SpecialistCard } from '@sosed/ui-web';
import { useRouter } from '@tanstack/react-router';

import { useCardArea } from './city.ts';
import type { FavoriteControl } from './favorite.ts';
import type { Language } from './paths.ts';
import { CARD_PATHS, LANGUAGES, profilePath } from './paths.ts';

const PHONE_VERIFIED = 'phone_verified';
/** Внизу карточки — не больше двух фактов: «Сегодня до …», потом «Телефон подтверждён».
 *  «Новый специалист» — текстом в строке рейтинга, «Подработка» — бейджем у имени. */
const MAX_BADGES = 2;

export function ResultCard({
  card,
  favorite,
  home = false,
}: {
  card: SpecialistCardOut;
  favorite?: FavoriteControl;
  /** Главная S03: число отзывов словом — «37 отзывов», как на артборде S03; в выдаче и
   *  избранном — «(37)», как на артборде S05. */
  home?: boolean;
}) {
  const { t } = useTranslation('catalog');
  const common = useTranslation().t;
  const format = useFormat();
  const router = useRouter();
  const now = new Date();
  const area = useCardArea(card);
  const place = [area, card.distance_m === null ? undefined : format.distance(card.distance_m)]
    .filter(Boolean)
    .join(', ');
  // не через card.ts: тот тянет прайс-хелперы в чанк блока Главной; незнакомый код не показываем
  const languages = card.languages
    .filter((code): code is Language => (LANGUAGES as readonly string[]).includes(code))
    .map((code) => t(`results.languages.${code}`))
    .join(', ');
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
  // единица — у той же позиции, что цена «от»: «от 1 000 RSD/час»; незнакомая — без единицы
  const unit = SERVICE_UNITS.find((known) => known === card.price_from_unit) ?? null;
  const price =
    card.price_from !== null
      ? format.price({ type: 'from', min: card.price_from, unit })
      : card.negotiable
        ? common('price.negotiable')
        : null;
  return (
    <SpecialistCard
      name={card.display_name}
      tag={card.kind === 'casual' ? t('results.casual') : null}
      headline={card.headline}
      photo={card.avatar ? { src: card.avatar.url, placeholder: card.avatar.placeholder } : null}
      rating={card.rating === null || card.is_new ? null : format.rating(card.rating)}
      reviews={t(home ? 'profile.reviews' : 'results.reviews', { count: card.rating_count })}
      newLabel={common('rating.new')}
      languages={languages || null}
      meta={place ? [place] : []}
      badges={badges.slice(0, MAX_BADGES)}
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
