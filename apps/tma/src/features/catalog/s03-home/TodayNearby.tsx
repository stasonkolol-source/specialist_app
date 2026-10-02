// «Свободны сегодня рядом» на S03 — отдельным чанком: карточки выдачи с фото, рейтингом и
// сердечком не нужны до первого кадра Главной, а пустой список чанк и не грузит (бюджет первого
// экрана 200 KB gzip, DEVELOPMENT_PLAN 0.21b).
import type { SpecialistCardOut } from '@sosed/api-client';
import { useTranslation } from '@sosed/i18n';
import { Banner, Heading, LinkButton } from '@sosed/ui-web';
import type { MouseEvent } from 'react';
import { useId } from 'react';

import { ResultCard } from '../shared/ResultCard.tsx';
import { useFavoriteToggle } from '../shared/favorite.ts';

export function TodayNearby({
  cards,
  allHref,
  onAll,
}: {
  cards: SpecialistCardOut[];
  /** «Все» — выдача «свободны сегодня», рядом — если известна точка. */
  allHref: string;
  onAll: (event?: MouseEvent<HTMLElement>) => void;
}) {
  const { t } = useTranslation('catalog');
  const { control, failure } = useFavoriteToggle();
  const todayId = useId();
  return (
    <>
      {failure && (
        <Banner tone="danger" role="alert">
          {failure}
        </Banner>
      )}
      <section aria-labelledby={todayId} className="flex flex-col gap-3">
        <div className="flex items-center justify-between gap-3">
          <Heading variant="h3" as="h2" id={todayId}>
            {t('home.today')}
          </Heading>
          <LinkButton href={allHref} onClick={onAll} className="-mr-2">
            {t('home.all')}
          </LinkButton>
        </div>
        {cards.map((card) => (
          <ResultCard key={card.profile_id} card={card} favorite={control(card)} />
        ))}
      </section>
    </>
  );
}
