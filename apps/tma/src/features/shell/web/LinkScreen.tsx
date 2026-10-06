// Веб-ссылка на карточку специалиста `/s/<id>` и заявку `/j/<id>` (8.1, ARCHITECTURE §11.4): вне
// Telegram — кого или что прислали: имя, рейтинг, район и фото специалиста или название, бюджет,
// срок и места заявки. Запрос тот же, что у гостевого S08 или S15, — экран потом откроется из
// кэша. Ниже — одна фраза о том, что написать можно в Telegram, «Открыть в Telegram» с кодом
// startapp сущности и «Посмотреть в браузере» — гостевой просмотр. Пока данные грузятся — скелетон
// той же формы; профиль скрыт, заявки нет или запрос упал — общий вариант без данных. Внутри
// Telegram такой адрес сразу открывает экран. Битая ссылка — корневая страница.
import type { CardWorkOut, JobOut, SpecialistProfileOut } from '@sosed/api-client';
import { budgetAsPrice, businessDay, responseSlots } from '@sosed/domain';
import { cardVariants, useCities, useDistricts, useJob, useSpecialistCard } from '@sosed/hooks';
import { useFormat, useLocale, useTranslation } from '@sosed/i18n';
import { usePlatform } from '@sosed/platform';
import {
  Avatar,
  Badge,
  Banner,
  Button,
  Card,
  EmptyState,
  Heading,
  Icon,
  Photo,
  Skeleton,
  SkeletonText,
  Text,
} from '@sosed/ui-web';
import { Navigate, useParams, useRouter } from '@tanstack/react-router';
import type { ReactNode } from 'react';

import { WebFooter } from './Footer.tsx';
import { OpenInTelegram } from './OpenInTelegram.tsx';
import type { WebEntity } from './links.ts';
import { ENTITY_PATHS, entityId, entityStart, telegramLink } from './links.ts';

/** Код startapp главной (packages/links). */
const HOME_START = 'h';
const PHONE_VERIFIED = 'phone_verified';
/** Аватар lg — 88 px. */
const AVATAR_LG = 88;
/** Фото в превью — не больше трёх, как превью работ на S08. */
const MAX_PHOTOS = 3;

/** Плитка фото — квадрат на всю ячейку ряда (PhotoRow). */
const TILE = 'aspect-square w-full';

const lowercased = (text: string) => text.charAt(0).toLowerCase() + text.slice(1);

export function SpecialistLinkScreen() {
  return <EntityLink type="specialist" />;
}

export function JobLinkScreen() {
  return <EntityLink type="job" />;
}

function EntityLink({ type }: { type: WebEntity }) {
  const { code = '' } = useParams({ strict: false }) as { code?: string };
  const platform = usePlatform();
  const id = entityId(code);
  if (id === null) return <OpenInTelegram start={HOME_START} />;
  if (platform.kind !== 'browser') return <Navigate to={ENTITY_PATHS[type](id)} replace />;
  return type === 'specialist' ? <SpecialistLink id={id} /> : <JobLink id={id} />;
}

function SpecialistLink({ id }: { id: string }) {
  const card = useSpecialistCard(id, useLocale());
  return (
    <LinkPage type="specialist" id={id} failed={!card.data && card.isError}>
      {card.data ? <SpecialistPreview card={card.data} /> : <PreviewSkeleton avatar />}
    </LinkPage>
  );
}

function JobLink({ id }: { id: string }) {
  const job = useJob(id);
  return (
    <LinkPage type="job" id={id} failed={!job.data && job.isError}>
      {job.data ? <JobPreview job={job.data} /> : <PreviewSkeleton avatar={false} />}
    </LinkPage>
  );
}

/** Страница ссылки: превью (или общий вариант, если данных не будет — профиль скрыт, заявки нет,
 *  запрос упал), фраза и две кнопки. Упавшее фоновое обновление превью не прячет. */
function LinkPage({
  type,
  id,
  failed,
  children,
}: {
  type: WebEntity;
  id: string;
  failed: boolean;
  children: ReactNode;
}) {
  const { t } = useTranslation('web');
  const router = useRouter();
  const href = telegramLink(entityStart(type, id));
  return (
    <div className="flex flex-1 flex-col gap-4 px-4 pt-3 pb-4">
      {failed ? (
        <EmptyState icon="send" title={t(`link.${type}`)} as="h1" size="h2">
          {t('link.text')}
        </EmptyState>
      ) : (
        <>
          {children}
          <Text secondary className="px-2 text-center text-balance">
            {t(`link.${type}Lead`)}
          </Text>
        </>
      )}
      <div className="flex flex-col gap-3">
        {href ? (
          <Button href={href} full icon="send">
            {t('link.open')}
          </Button>
        ) : (
          <Banner tone="info">{t('link.noBot')}</Banner>
        )}
        <Button
          variant="outline"
          full
          onClick={() => void router.navigate({ to: ENTITY_PATHS[type](id) })}
        >
          {t('link.view')}
        </Button>
      </div>
      <WebFooter />
    </div>
  );
}

/** Кого прислали: аватар, имя, «коротко о себе», рейтинг и район, «Телефон подтверждён», работы. */
function SpecialistPreview({ card }: { card: SpecialistProfileOut }) {
  const { t } = useTranslation('catalog');
  const { t: common } = useTranslation();
  const format = useFormat();
  // выезжает во все районы — «Весь Нови-Сад», а не первый по алфавиту квартал (QA SMOKE-6)
  const place =
    card.whole_city && card.city
      ? common('place.wholeCity', { city: card.city.name })
      : (card.district?.name ?? card.city?.name ?? null);
  return (
    <Card as="section" className="items-center text-center">
      <Avatar
        name={card.display_name}
        size="lg"
        src={avatarSrc(card, AVATAR_LG)}
        placeholder={card.avatar?.placeholder}
        priority
      />
      <div className="flex flex-col gap-1">
        <Heading variant="h1" as="h1" className="text-balance">
          {card.display_name}
        </Heading>
        {card.headline && <Text secondary>{card.headline}</Text>}
      </div>
      <p className="m-0 flex flex-wrap items-center justify-center gap-1.5 text-cap text-text2">
        {card.rating !== null && !card.is_new ? (
          <>
            <span className="inline-flex items-center gap-0.75 font-semibold text-text">
              <Icon name="star" size={16} className="text-star" />
              {format.rating(card.rating)}
            </span>
            <span aria-hidden="true">·</span>
            <span>{common('count.reviews', { count: card.rating_count })}</span>
          </>
        ) : (
          <span>{common('rating.new')}</span>
        )}
        {place && (
          <>
            <span aria-hidden="true">·</span>
            <span>{place}</span>
          </>
        )}
      </p>
      {card.badges.includes(PHONE_VERIFIED) && (
        <Badge tone="info" icon="shield">
          {t('results.phoneVerified')}
        </Badge>
      )}
      <Works works={card.works.slice(0, MAX_PHOTOS)} />
    </Card>
  );
}

/** До трёх работ квадратами — как превью работ на S08 (без ссылок: смотреть — на S10). */
function Works({ works }: { works: readonly CardWorkOut[] }) {
  const { t } = useTranslation('catalog');
  if (works.length === 0) return null;
  return (
    <PhotoRow count={works.length}>
      {works.map((work, index) => {
        const title = work.caption ?? t('profile.work', { number: index + 1 });
        return (
          <Photo
            key={work.id}
            variants={cardVariants(work.photo)}
            placeholder={work.photo.placeholder}
            sizes="33vw"
            alt={work.kind === 'video' ? t('profile.video', { title }) : title}
            video={work.kind === 'video'}
            className={TILE}
          />
        );
      })}
    </PhotoRow>
  );
}

/** Что прислали: название заявки, бюджет и срок, район и места, до трёх фото. */
function JobPreview({ job }: { job: JobOut }) {
  const { t } = useTranslation('jobs');
  const { t: common } = useTranslation();
  const format = useFormat();
  const when = useWhenText();
  const place = useJobPlace(job);
  const slots = responseSlots({
    maxResponses: job.max_responses,
    responsesCount: job.responses_count,
  });
  const budget =
    job.budget_type === 'negotiable'
      ? t('card.negotiable')
      : format.price(
          budgetAsPrice({
            type: job.budget_type,
            min: job.budget_min?.amount ?? null,
            max: job.budget_max?.amount ?? null,
            unit: job.budget_unit,
          }),
        );
  const photos = job.photos.slice(0, MAX_PHOTOS);
  return (
    <Card as="section" className="items-center text-center">
      <Heading variant="h1" as="h1" className="text-balance">
        {job.title}
      </Heading>
      <div className="flex flex-col gap-0.5">
        <Text bold>{`${budget} · ${lowercased(when(job))}`}</Text>
        <Text variant="cap">
          {[place, common('count.responsesOf', { count: slots.taken, total: slots.total })]
            .filter(Boolean)
            .join(' · ')}
        </Text>
      </div>
      {photos.length > 0 && (
        <PhotoRow count={photos.length}>
          {photos.map((photo, index) => (
            <Photo
              key={photo.url}
              src={photo.url}
              placeholder={photo.placeholder}
              sizes="33vw"
              alt={t('job.photo', { number: index + 1, total: job.photos.length })}
              className={TILE}
            />
          ))}
        </PhotoRow>
      )}
    </Card>
  );
}

/** Скелетон превью той же формы: аватар (у специалиста), заголовок, две строки и фото. */
function PreviewSkeleton({ avatar }: { avatar: boolean }) {
  return (
    <div aria-busy="true" className="flex flex-col items-center gap-3 rounded-card bg-surface p-4">
      {avatar && <Skeleton round className="size-22" />}
      <SkeletonText size="h1" className="w-3/5" />
      <div className="flex w-full flex-col items-center gap-0.5">
        <SkeletonText size="body" className="w-4/5" />
        <SkeletonText size="cap" className="w-1/2" />
      </div>
      <PhotoRow count={MAX_PHOTOS}>
        {Array.from({ length: MAX_PHOTOS }, (_, index) => (
          <Skeleton key={index} radius="field" className={TILE} />
        ))}
      </PhotoRow>
    </div>
  );
}

/** Ряд фото превью: ячейка — треть ряда (два зазора по 8 px); одно-два фото — по центру, а не
 *  прижаты к левому краю. Ширина ячейки — стилем элемента: свой класс лёг бы в общий CSS первого
 *  экрана. */
function PhotoRow({ count, children }: { count: number; children: ReactNode }) {
  return (
    <div
      className="grid w-full justify-center gap-2"
      style={{ gridTemplateColumns: `repeat(${count}, calc((100% - 1rem) / 3))` }}
    >
      {children}
    </div>
  );
}

/** Фото для аватара `size` px: самый маленький вариант, которого хватит экрану плотностью 3x (как
 *  в шапке S08 — тот же файл из кэша браузера). */
function avatarSrc(card: SpecialistProfileOut, size: number): string | undefined {
  const variants = [...(card.avatar?.variants ?? [])].sort((a, b) => a.width - b.width);
  return (variants.find((variant) => variant.width >= size * 3) ?? variants.at(-1))?.url;
}

/** Срок заявки, как бейдж «когда» на S13 и S15: «Срочно», «Сегодня 18:00–21:00» (только в тот же
 *  день по Белграду), дата, «На неделе». */
function useWhenText(): (job: JobOut) => string {
  const { t } = useTranslation('jobs');
  const { t: common } = useTranslation();
  const format = useFormat();
  return (job) => {
    if (job.urgency === 'asap') return common('urgency.asap');
    const from = job.preferred_from ? new Date(job.preferred_from) : null;
    const to = job.preferred_to ? new Date(job.preferred_to) : null;
    const now = new Date();
    if (from && to && job.urgency === 'today' && businessDay(from) === businessDay(now)) {
      return t('card.todaySlot', { from: format.time(from), to: format.time(to) });
    }
    if (from) return format.calendar(from, now);
    return common(`urgency.${job.urgency}`);
  };
}

/** Район заявки по справочнику города; без района — город. */
function useJobPlace(job: JobOut): string | null {
  const locale = useLocale();
  const districts = useDistricts(job.city_id, locale).data;
  const city = useCities(locale).data?.find((item) => item.id === job.city_id);
  return districts?.find((item) => item.id === job.district_id)?.name ?? city?.name ?? null;
}
