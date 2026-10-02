// S08 Профиль специалиста (DEVELOPMENT_PLAN 4.5): экран, на котором клиент решает, писать ли.
// Шапка — фото, имя, «коротко о себе», рейтинг или «Новый специалист», район, сердечко «в
// избранное» (4.6); бейджи «Сегодня до …» и «Телефон подтверждён»; памятка «не платите предоплату
// незнакомым»; первые позиции прайса со ссылкой на S09, превью работ со ссылкой на просмотрщик S10,
// последний отзыв со ссылкой на S11; «О себе» — текст, языки и районы выезда. Всё — одним запросом
// BFF. Профиль скрыт или его нет — «Профиль недоступен». Скрыто до своих шагов: MainButton
// «Написать …» (прямой запрос 5.6, диалог 6.4), «Предложить заявку» (5.6), «Поделиться» (7.4),
// «Обычно отвечает за …» (6.3b), «Пожаловаться» и «Заблокировать» (4.7). Гость видит экран без
// входа, но без сердечка.
import type { CardWorkOut, SpecialistProfileOut } from '@sosed/api-client';
import { cardVariants, isUnavailable, searchCardOf, useSpecialistCard } from '@sosed/hooks';
import { useFormat, useLocale, useTranslation } from '@sosed/i18n';
import { useBackButton } from '@sosed/platform';
import {
  Avatar,
  Badge,
  Banner,
  Card,
  Group,
  Heading,
  Icon,
  IconButton,
  LinkButton,
  Photo,
  Price,
  Row,
  Skeleton,
  Text,
} from '@sosed/ui-web';
import { useParams, useRouter } from '@tanstack/react-router';
import type { MouseEvent, ReactNode } from 'react';
import { useId } from 'react';

import { LoadError } from '../shared/LoadError.tsx';
import { ReviewCard } from '../shared/ReviewCard.tsx';
import { Unavailable } from '../shared/Unavailable.tsx';
import { avatarSrc, knownLanguages, place, priceAmount, sentence } from '../shared/card.ts';
import { useFavoriteToggle } from '../shared/favorite.ts';
import { CARD_PATHS } from '../shared/paths.ts';

const PHONE_VERIFIED = 'phone_verified';
/** Аватар lg — 88 px. */
const AVATAR_LG = 88;

export function SpecialistScreen() {
  const { profileId } = useParams({ strict: false }) as { profileId: string };
  const router = useRouter();
  const card = useSpecialistCard(profileId, useLocale());
  useBackButton(() => {
    if (router.history.canGoBack()) router.history.back();
    else void router.navigate({ to: '/', replace: true });
  });

  if (card.data) return <Profile card={card.data} />;
  if (card.isError) {
    return isUnavailable(card.error) ? (
      <Unavailable />
    ) : (
      <section className="flex flex-col px-4 pt-3 pb-6">
        <LoadError
          error={card.error}
          onRetry={() => void card.refetch()}
          retrying={card.isRefetching}
        />
      </section>
    );
  }
  return (
    <section className="flex flex-col gap-3.5 px-4 pt-3 pb-6" aria-busy="true">
      <Skeleton className="h-40 w-full" />
      <Skeleton className="h-16 w-full" />
      <Skeleton className="h-44 w-full" />
    </section>
  );
}

function Profile({ card }: { card: SpecialistProfileOut }) {
  const { t } = useTranslation('catalog');
  const common = useTranslation().t;
  const format = useFormat();
  const router = useRouter();
  const pricesId = useId();
  const worksId = useId();
  const reviewsId = useId();
  const aboutId = useId();
  const { control, failure } = useFavoriteToggle();
  const favorite = control(searchCardOf(card), false);
  const params = { profileId: card.id };
  const go = (to: string, search?: { work: string }) => (event: MouseEvent<HTMLElement>) => {
    event.preventDefault();
    void router.navigate({ to, params, search });
  };
  // у hash history в Telegram ссылка — «#/specialists/…»: адрес маршрута → href ссылки
  const href = (to: string, search?: { work: string }) =>
    router.history.createHref(router.buildLocation({ to, params, search }).href);

  const until = card.available_until ? new Date(card.available_until) : null;
  const today = until !== null && until > new Date();
  const languages = knownLanguages(card).map((code) => t(`profile.languageNames.${code}`));
  const areas = card.areas.map((area) => area.name);
  const travel =
    areas.length > 0
      ? t('profile.travel', { areas: areas.join(', ') })
      : card.travel_radius_km
        ? t('profile.radius', { km: card.travel_radius_km })
        : null;
  const where = place(card);

  return (
    <section className="flex flex-col gap-3.5 px-4 pt-3 pb-6">
      <Card as="section" className="relative">
        {favorite && (
          <IconButton
            plain
            icon="heart"
            label={favorite.label}
            active={favorite.active}
            aria-pressed={favorite.active}
            onClick={favorite.onToggle}
            className="absolute top-1 right-1"
          />
        )}
        <div className="flex items-center gap-4">
          <Avatar
            name={card.display_name}
            size="lg"
            src={avatarSrc(card.avatar, AVATAR_LG)}
            placeholder={card.avatar?.placeholder}
          />
          <div className="flex min-w-0 grow flex-col gap-1">
            <Heading variant="h2" as="h1" className={favorite && 'pr-8'}>
              {card.display_name}
            </Heading>
            {card.headline && (
              <Text variant="sm" secondary>
                {card.headline}
              </Text>
            )}
            <p className="m-0 flex flex-wrap items-center gap-1.5 text-cap text-text2">
              {card.rating === null || card.is_new ? (
                <span>{common('rating.new')}</span>
              ) : (
                <>
                  <span className="inline-flex items-center gap-0.75 font-semibold text-text">
                    <Icon name="star" size={16} className="text-star" />
                    {format.rating(card.rating)}
                  </span>
                  <span>{t('profile.reviews', { count: card.rating_count })}</span>
                </>
              )}
            </p>
            {where && <p className="m-0 text-cap text-text2">{where}</p>}
          </div>
        </div>
        {(card.badges.includes(PHONE_VERIFIED) || today) && (
          <div className="flex flex-wrap gap-1.5">
            {card.badges.includes(PHONE_VERIFIED) && (
              <Badge tone="info" icon="shield">
                {t('results.phoneVerified')}
              </Badge>
            )}
            {today && until && (
              <Badge tone="ok" dot>
                {t('results.todayUntil', { time: format.time(until) })}
              </Badge>
            )}
          </div>
        )}
      </Card>
      {failure && (
        <Banner tone="danger" role="alert">
          {failure}
        </Banner>
      )}
      <Banner tone="warn">{t('profile.prepayment')}</Banner>
      {card.services_count > 0 && (
        <section aria-labelledby={pricesId} className="flex flex-col gap-2">
          <SectionHead
            id={pricesId}
            title={t('profile.prices')}
            link={t('profile.allPrices', { count: card.services_count })}
            href={href(CARD_PATHS.services)}
            onClick={go(CARD_PATHS.services)}
          />
          <Group>
            {card.services.map((service) => (
              <Row
                key={service.id}
                title={service.title}
                trailing={<Price>{priceAmount(format, service)}</Price>}
              />
            ))}
          </Group>
        </section>
      )}
      {card.works_count > 0 && (
        <section aria-labelledby={worksId} className="flex flex-col gap-2">
          <SectionHead
            id={worksId}
            title={t('profile.works')}
            link={t('profile.allWorks', { count: card.works_count })}
            href={href(CARD_PATHS.portfolio)}
            onClick={go(CARD_PATHS.portfolio)}
          />
          <div className="grid grid-cols-3 gap-2">
            {card.works.map((work, index) => (
              <WorkTile
                key={work.id}
                work={work}
                number={index + 1}
                href={href(CARD_PATHS.portfolio, { work: work.id })}
                onClick={go(CARD_PATHS.portfolio, { work: work.id })}
              />
            ))}
          </div>
        </section>
      )}
      {card.rating_count > 0 && (
        <section aria-labelledby={reviewsId} className="flex flex-col gap-2">
          <SectionHead
            id={reviewsId}
            title={t('reviews.title')}
            link={t('reviews.all', { count: card.rating_count })}
            href={href(CARD_PATHS.reviews)}
            onClick={go(CARD_PATHS.reviews)}
          />
          {card.reviews.map((review) => (
            <ReviewCard key={review.id} review={review} />
          ))}
        </section>
      )}
      {(card.about || languages.length > 0 || travel) && (
        <section
          aria-labelledby={aboutId}
          className="flex flex-col gap-2 rounded-card bg-surface p-4 text-text"
        >
          <Heading variant="h3" as="h2" id={aboutId}>
            {t('profile.about')}
          </Heading>
          {card.about && (
            <Text variant="sm" className="whitespace-pre-line">
              {card.about}
            </Text>
          )}
          {card.about && (languages.length > 0 || travel) && (
            <div className="h-px bg-line" aria-hidden="true" />
          )}
          {languages.length > 0 && <Meta icon="languages">{sentence(languages)}</Meta>}
          {travel && <Meta icon="pin">{travel}</Meta>}
        </section>
      )}
    </section>
  );
}

function SectionHead({
  id,
  title,
  link,
  href,
  onClick,
}: {
  id: string;
  title: string;
  link: string;
  href: string;
  onClick: (event: MouseEvent<HTMLElement>) => void;
}) {
  return (
    <div className="flex items-center justify-between gap-3 px-1">
      <Heading variant="h3" as="h2" id={id}>
        {title}
      </Heading>
      <LinkButton href={href} onClick={onClick} className="-mr-2">
        {link}
      </LinkButton>
    </div>
  );
}

function WorkTile({
  work,
  number,
  href,
  onClick,
}: {
  work: CardWorkOut;
  number: number;
  href: string;
  onClick: (event: MouseEvent<HTMLElement>) => void;
}) {
  const { t } = useTranslation('catalog');
  const title = work.caption ?? t('profile.work', { number });
  const video = work.kind === 'video';
  return (
    <a
      href={href}
      onClick={onClick}
      aria-label={video ? t('profile.video', { title }) : title}
      className="block rounded-photo outline-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
    >
      <Photo
        variants={cardVariants(work.photo)}
        placeholder={work.photo.placeholder}
        sizes="33vw"
        alt={title}
        video={video}
        className="aspect-square w-full"
      />
    </a>
  );
}

function Meta({ icon, children }: { icon: 'languages' | 'pin'; children: ReactNode }) {
  return (
    <p className="m-0 flex items-center gap-1.5 text-cap text-text2">
      <Icon name={icon} size={16} />
      {children}
    </p>
  );
}
