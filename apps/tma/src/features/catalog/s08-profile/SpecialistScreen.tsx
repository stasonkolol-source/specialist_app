// S08 Профиль специалиста (DEVELOPMENT_PLAN 4.5): экран, на котором клиент решает, писать ли.
// Шапка — фото, имя, «коротко о себе», рейтинг или «Новый специалист», район и «Обычно отвечает
// за …» (когда диалогов с ответом за 30 дней набралось пять); бейджи — не больше трёх:
// «Подработка», «Телефон подтверждён», «Сегодня до …»; под ними ряд кнопок, как на артборде:
// «Предложить заявку», сердечко «в избранное» (4.6) и «Поделиться». Памятка «не платите
// предоплату незнакомым»; первые позиции прайса с единицей у суммы и ссылкой на S09, превью работ
// со ссылкой на просмотрщик S10, последний отзыв со ссылкой на S11; «О себе» — текст, языки и
// районы выезда. Всё — одним запросом BFF. Профиль скрыт или его нет — «Профиль недоступен».
// MainButton «Написать» (6.4) — диалог S30 со специалистом (начатый — тот же); «Предложить
// заявку» — прямой запрос (5.6): мастер заявки S20a, заявку увидит только этот специалист. На
// своём профиле обеих кнопок и сердечка нет. Внизу (4.7) — «Пожаловаться на профиль» (шторка S46;
// пока она открыта, MainButton спрятана) и «Заблокировать» с подтверждением: заблокированному не
// написать и не предложить заявку — вместо кнопок памятка и «Разблокировать». Меню «⋯» артборда —
// часть шапки Telegram, своих пунктов в нём у Mini App нет: действия — строками, как «Пожаловаться
// на профиль» на артборде. «Поделиться» (7.4) — всем: карточка в выбор чата Telegram или ссылка (у
// гостя — без кода приглашения). Гость видит экран без входа, но без сердечка, жалобы и
// блокировки; «Написать» гостю — тоже мастер заявки: диалог начинается после входа. В браузере
// (8.1) вместо обеих кнопок — одна «Написать в Telegram»: ссылка сразу на этот профиль в Mini App
// (telegram.ts); без бота в сборке — прежняя «Написать».
import type { CardWorkOut, SpecialistCardOut, SpecialistProfileOut } from '@sosed/api-client';
import { getSession } from '@sosed/api-client';
import { color } from '@sosed/design-tokens';
import {
  blockedIds,
  blockedUserOf,
  cachedSpecialistCard,
  cardVariants,
  isUnavailable,
  openReport,
  searchCardOf,
  useBlocks,
  useMyProfile,
  useReportTarget,
  useSpecialistCard,
  useStartConversation,
  useToggleBlock,
} from '@sosed/hooks';
import type { Format } from '@sosed/i18n';
import { useFormat, useLocale, useTranslation } from '@sosed/i18n';
import { useBackButton, useColorScheme, useMainButton, usePlatform } from '@sosed/platform';
import {
  Avatar,
  Badge,
  Banner,
  Button,
  Card,
  Group,
  Heading,
  Icon,
  IconButton,
  LinkButton,
  Photo,
  Row,
  RowsSkeleton,
  Skeleton,
  SkeletonCard,
  SkeletonText,
  Text,
} from '@sosed/ui-web';
import type { SpecialistBadge } from '@sosed/ui-web';
import { useQueryClient } from '@tanstack/react-query';
import { useParams, useRouter } from '@tanstack/react-router';
import type { MouseEvent, ReactNode } from 'react';
import { useId } from 'react';

import { LoadError } from '../shared/LoadError.tsx';
import { ReviewCard } from '../shared/ReviewCard.tsx';
import { Unavailable } from '../shared/Unavailable.tsx';
import { PriceColumn } from '../s09-prices/PriceColumn.tsx';
import { avatarSrc, knownLanguages, place, sentence } from '../shared/card.ts';
import { useCardArea, useWholeCity } from '../shared/city.ts';
import { useFavoriteToggle } from '../shared/favorite.ts';
import { useProfileShare } from '../shared/share.tsx';
import { CARD_PATHS, CREATE_JOB_PATH, chatPath } from '../shared/paths.ts';
import { writeInTelegramLink } from './telegram.ts';

const PHONE_VERIFIED = 'phone_verified';
const CASUAL = 'casual';
/** Аватар lg — 88 px. */
const AVATAR_LG = 88;
const MINUTES_IN_HOUR = 60;
/** Бейджей в шапке — не больше трёх: дальше ряд переносится и спорит с кнопками. */
const MAX_BADGES = 3;

export function SpecialistScreen() {
  const { profileId } = useParams({ strict: false }) as { profileId: string };
  const router = useRouter();
  const card = useSpecialistCard(profileId, useLocale());
  const queryClient = useQueryClient();
  useBackButton(() => {
    if (router.history.canGoBack()) router.history.back();
    else void router.navigate({ to: '/', replace: true });
  });

  if (isUnavailable(card.error)) return <Unavailable />;
  if (card.data) return <Profile card={card.data} />;
  if (card.isError) {
    return (
      <section className="flex flex-col px-4 pt-3 pb-6">
        <LoadError
          error={card.error}
          onRetry={() => void card.refetch()}
          retrying={card.isRefetching}
        />
      </section>
    );
  }
  return <Loading preview={cachedSpecialistCard(queryClient, profileId)} />;
}

/** Профиль ещё грузится. Открыли из выдачи, «Свободны сегодня» или избранного — шапка из их
 *  карточки (фото, имя, «коротко о себе», рейтинг, район): то, что человек уже видел. Сердечко,
 *  «Предложить заявку», «Написать» и остальное — только по полному профилю. */
function Loading({ preview }: { preview: SpecialistCardOut | undefined }) {
  return (
    <section className="flex flex-col gap-3.5 px-4 pt-3 pb-6" aria-busy="true">
      {preview ? (
        <Card as="section">
          <PreviewHead card={preview} />
          <Skeleton radius="field" className="h-11 w-full" />
        </Card>
      ) : (
        <SkeletonCard>
          <div className="flex items-center gap-4">
            <Skeleton round className="size-22 shrink-0" />
            <div className="flex min-w-0 grow flex-col gap-1">
              <SkeletonText size="h2" className="w-3/5" />
              <SkeletonText size="sm" className="w-4/5" />
              <SkeletonText size="cap" className="w-1/2" />
            </div>
          </div>
          <Skeleton radius="field" className="h-11 w-full" />
        </SkeletonCard>
      )}
      <SkeletonText size="h3" screen className="w-1/3" />
      <RowsSkeleton rows={3} leading="none" subtitle={false} trailing />
    </section>
  );
}

/** Шапка из карточки списка: та же раскладка, что у профиля. */
function PreviewHead({ card }: { card: SpecialistCardOut }) {
  const { t } = useTranslation('catalog');
  const { t: common } = useTranslation();
  const format = useFormat();
  const area = useCardArea(card);
  return (
    <div className="flex items-center gap-4">
      <Avatar
        name={card.display_name}
        size="lg"
        src={card.avatar?.url}
        placeholder={card.avatar?.placeholder}
        priority
      />
      <div className="flex min-w-0 grow flex-col gap-1">
        <Heading variant="h2" as="h1">
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
        {area && <p className="m-0 text-cap text-text2">{area}</p>}
      </div>
    </div>
  );
}

/** MainButton «Написать»: диалог S30 со специалистом; гостю — прямой запрос через мастер заявки
 *  (написать без входа нечем); себе и заблокированному — не пишут; пока открыта шторка жалобы или
 *  в браузере вместо неё ссылка в Telegram — кнопки нет (`hidden`). Возвращает, свой ли это
 *  профиль. */
function useWriteButton(profileId: string, hidden: boolean) {
  const { t: common } = useTranslation();
  const router = useRouter();
  const scheme = useColorScheme();
  const palette = color[scheme];
  const signedIn = getSession() !== null;
  const own = useMyProfile({ enabled: signedIn }).data?.id === profileId;
  const start = useStartConversation();
  const write = () =>
    start.mutate(
      { profile_id: profileId },
      { onSuccess: (started) => void router.navigate({ to: chatPath(started.id) }) },
    );
  useMainButton({
    text: common('action.write'),
    visible: !own && !hidden,
    enabled: !start.isPending,
    loading: start.isPending,
    color: palette.accent,
    textColor: palette['accent-ink'],
    onClick: () =>
      signedIn
        ? write()
        : void router.navigate({ to: CREATE_JOB_PATH, search: { direct: profileId } }),
  });
  return { own, writeError: start.error };
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
  const sharing = useProfileShare(card.id);
  const blocks = useBlocks();
  const blocked = blockedIds(blocks.data).has(card.user_id);
  const reporting = useReportTarget() !== null;
  // браузер (только гость): написать можно лишь в Telegram — кнопка сразу ведёт туда
  const browser = usePlatform().kind === 'browser';
  const telegram = browser ? writeInTelegramLink(card.id) : null;
  const { own, writeError } = useWriteButton(card.id, blocked || reporting || telegram !== null);
  // себе и заблокированному — только «Поделиться»; в браузере заявку не предложить (мастера нет)
  const favorite = own || blocked ? undefined : control(searchCardOf(card), false);
  const propose = !own && !blocked && !browser;
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
  const wholeCity = useWholeCity(card.city?.name);
  // все районы города — «Выезд: Весь Нови-Сад», а не список из 27 кварталов (QA SMOKE-6)
  const areas = card.whole_city ? [wholeCity] : card.areas.map((area) => area.name);
  const response = responseTime(card.response_time_minutes, t);
  const badges = headerBadges(card, today ? until : null, t, format);
  const travel =
    areas.length > 0
      ? t('profile.travel', { areas: areas.join(', ') })
      : card.travel_radius_km
        ? t('profile.radius', { km: card.travel_radius_km })
        : null;
  const where = place(card, wholeCity);

  return (
    <section className={`flex flex-col gap-3.5 px-4 pt-3 ${telegram ? 'pb-25' : 'pb-6'}`}>
      <Card as="section">
        <div className="flex items-center gap-4">
          <Avatar
            name={card.display_name}
            size="lg"
            src={avatarSrc(card.avatar, AVATAR_LG)}
            placeholder={card.avatar?.placeholder}
            priority
          />
          <div className="flex min-w-0 grow flex-col gap-1">
            <Heading variant="h2" as="h1">
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
            {response && <Meta icon="clock">{response}</Meta>}
          </div>
        </div>
        {badges.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {badges.map((badge) => (
              <Badge key={badge.label} tone={badge.tone} icon={badge.icon} dot={badge.dot}>
                {badge.label}
              </Badge>
            ))}
          </div>
        )}
        {/* ряд как на артборде: кнопка тянется, иконки 44×44 справа; без кнопки иконки — там же */}
        <div className="flex justify-end gap-2">
          {propose && (
            <Button
              variant="outline"
              className="flex-1"
              onClick={() =>
                void router.navigate({ to: CREATE_JOB_PATH, search: { direct: card.id } })
              }
            >
              {t('profile.proposeJob')}
            </Button>
          )}
          {favorite && (
            <IconButton
              icon="heart"
              label={favorite.label}
              active={favorite.active}
              aria-pressed={favorite.active}
              onClick={favorite.onToggle}
            />
          )}
          <IconButton
            icon="share"
            label={common('share.profile')}
            aria-busy={sharing.pending || undefined}
            onClick={sharing.share}
          />
        </div>
      </Card>
      {blocked && (
        <Banner tone="info" icon="ban" role="status">
          {t('profile.blocked')}
        </Banner>
      )}
      {writeError && (
        <Banner tone="danger" role="alert">
          {t('profile.writeFailed')}
        </Banner>
      )}
      {failure && (
        <Banner tone="danger" role="alert">
          {failure}
        </Banner>
      )}
      {sharing.notice}
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
                trailing={<PriceColumn service={service} />}
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
      {!own && getSession() !== null && <Safety card={card} blocked={blocked} />}
      {telegram && <WriteInTelegram href={telegram} />}
    </section>
  );
}

/** Кнопка гостя в браузере — на месте MainButton в контенте (ContentMainButton оболочки: внизу
 *  экрана, 76 px; отступ под неё — `pb-25` экрана), но ссылкой в Telegram с иконкой, как
 *  «Откликнуться в Telegram» на S15. */
function WriteInTelegram({ href }: { href: string }) {
  const { t } = useTranslation('catalog');
  return (
    <div className="fixed inset-x-0 bottom-0 z-50 mx-auto max-w-lg bg-bg px-4 py-3">
      <Button full icon="send" href={href}>
        {t('profile.writeInTelegram')}
      </Button>
    </div>
  );
}

/** Бейджи шапки — факты в порядке важности, не больше трёх: «Подработка» (S32a обещает
 *  специалисту пометку рядом с именем; SPEC §4 — `bdg mute`), «Телефон подтверждён», «Сегодня до
 *  …» (`until` — только пока ещё доступен). */
function headerBadges(
  card: Pick<SpecialistProfileOut, 'kind' | 'badges'>,
  until: Date | null,
  t: ReturnType<typeof useTranslation<'catalog'>>['t'],
  format: Format,
): SpecialistBadge[] {
  const badges: SpecialistBadge[] = [];
  if (card.kind === CASUAL) badges.push({ label: t('profile.casual'), tone: 'mute' });
  if (card.badges.includes(PHONE_VERIFIED)) {
    badges.push({ label: t('results.phoneVerified'), tone: 'info', icon: 'shield' });
  }
  if (until) {
    badges.push({
      label: t('results.todayUntil', { time: format.time(until) }),
      tone: 'ok',
      dot: true,
    });
  }
  return badges.slice(0, MAX_BADGES);
}

/** «Пожаловаться на профиль» (шторка S46) и «Заблокировать» с подтверждением или
 *  «Разблокировать» (4.7): строками внизу карточки — только вошедшему и не на своём профиле. */
function Safety({ card, blocked }: { card: SpecialistProfileOut; blocked: boolean }) {
  const { t } = useTranslation('catalog');
  const { t: common } = useTranslation();
  const platform = usePlatform();
  const toggle = useToggleBlock();
  const user = blockedUserOf({
    user_id: card.user_id,
    display_name: card.display_name,
    avatar: card.avatar,
    profile_id: card.id,
  });
  const block = async () => {
    if (blocked) toggle.mutate({ user, on: false });
    else if (await platform.confirm(t('profile.blockConfirm'))) toggle.mutate({ user, on: true });
  };
  return (
    <>
      {toggle.isError && (
        <Banner tone="danger" role="alert">
          {t('profile.blockFailed')}
        </Banner>
      )}
      <Group>
        <Row
          icon="flag"
          title={t('profile.report')}
          chevron
          onClick={() =>
            openReport({
              type: 'profile',
              id: card.id,
              userId: card.user_id,
              name: card.display_name,
              profileId: card.id,
            })
          }
        />
        <Row
          icon="ban"
          title={blocked ? common('action.unblock') : common('action.block')}
          onClick={() => void block()}
        />
      </Group>
    </>
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
      className="block rounded-photo outline-none focus-visible:outline-2 focus-visible:outline-solid focus-visible:outline-offset-2 focus-visible:outline-accent"
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

/** «Обычно отвечает за 15 минут»; от часа — часами. */
function responseTime(
  minutes: number | null | undefined,
  t: ReturnType<typeof useTranslation<'catalog'>>['t'],
): string | null {
  if (minutes == null) return null;
  if (minutes < MINUTES_IN_HOUR) return t('profile.responseMinutes', { count: minutes });
  return t('profile.responseHours', { count: Math.round(minutes / MINUTES_IN_HOUR) });
}

/** Строка с иконкой: иконка — у первой строки, как на артборде: длинное «Выезд: …» или сербское
 *  «Obično odgovori za …» в узкой шапке переносится, а иконка не съезжает в середину. */
function Meta({ icon, children }: { icon: 'languages' | 'pin' | 'clock'; children: ReactNode }) {
  return (
    <p className="m-0 flex items-start gap-1.5 text-cap text-text2">
      <Icon name={icon} size={16} className="mt-px shrink-0" />
      {children}
    </p>
  );
}
