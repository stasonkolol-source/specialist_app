// S15 Заявка (DEVELOPMENT_PLAN 5.3): то, по чему исполнитель решает, откликаться ли. Фото, «когда»
// и категория, заголовок, бюджет с единицей, «15 мин назад», места «Откликов 3 из 5 · осталось 2
// места»; описание и язык общения; «Где» — район на схеме (точка смещена на 300–500 м) и «≈ 1,2 км
// от вас», если лента знала точку; заказчик — имя, сколько он в «Соседях», сколько заявок
// публиковал, «Телефон подтверждён». Сердечко сохраняет заявку (сегмент «Задачи» S12), «Не
// интересно» убирает её из ленты навсегда — оба только вошедшему. Чужая
// неопубликованная или удалённая заявка — «Заявка недоступна». Своя — с пометкой «так её видят
// исполнители» (экран владельца S23 — 5.6). Открывается из ленты и по ссылке `startapp=j_…`; гость
// видит экран без входа. Скрыто до своих шагов: MainButton «Откликнуться · осталось N мест» (форма
// отклика — 5.5), «Поделиться» (7.4), «Пожаловаться» (S46, 4.7).
import type { JobOut } from '@sosed/api-client';
import { ApiError, getSession } from '@sosed/api-client';
import {
  distanceMeters,
  isUnavailable,
  jobQueryKey,
  selectableDistricts,
  useCities,
  useCategories,
  useDistricts,
  jobCardOf,
  savedJobIds,
  useHideJob,
  useSavedJobs,
  useToggleSavedJob,
  useJob,
} from '@sosed/hooks';
import { useFormat, useLocale, useTranslation } from '@sosed/i18n';
import { useBackButton, usePlatform } from '@sosed/platform';
import {
  Avatar,
  Badge,
  Banner,
  Button,
  Card,
  EmptyState,
  Heading,
  Icon,
  IconButton,
  MapPreview,
  Photo,
  Price,
  Skeleton,
  Text,
} from '@sosed/ui-web';
import { useParams, useRouter, useSearch } from '@tanstack/react-router';
import { useQueryClient } from '@tanstack/react-query';
import { useId } from 'react';

import { LoadError } from '../shared/LoadError.tsx';
import { findCategory } from '../shared/categories.ts';
import { useBudgetText, useMemberFor, useWhenBadge } from '../shared/labels.ts';
import type { JobSearch } from '../shared/paths.ts';
import { JOBS_PATHS, jobIdOf } from '../shared/paths.ts';

const LANGUAGE_NAMES = ['ru', 'sr', 'en'] as const;
type LanguageName = (typeof LANGUAGE_NAMES)[number];

const capitalized = (text: string) => text.charAt(0).toUpperCase() + text.slice(1);
const SAVED_FULL = 'saved_jobs_full';
const MAX_SAVED = 100;

export function JobScreen() {
  const { jobId: raw = '' } = useParams({ strict: false });
  const jobId = jobIdOf(raw);
  const job = useJob(jobId);
  const router = useRouter();
  const toFeed = () => {
    if (router.history.canGoBack()) router.history.back();
    else void router.navigate({ to: JOBS_PATHS.feed, replace: true });
  };
  useBackButton(toFeed);

  if (jobId === null || (job.isError && isUnavailable(job.error))) {
    return <Unavailable onFeed={() => void router.navigate({ to: JOBS_PATHS.feed })} />;
  }
  if (job.isError) {
    return (
      <section className="px-4 pt-6">
        <LoadError
          error={job.error}
          onRetry={() => void job.refetch()}
          retrying={job.isRefetching}
        />
      </section>
    );
  }
  if (!job.data) return <Loading />;
  return <Job job={job.data} onHidden={toFeed} />;
}

function Job({ job, onHidden }: { job: JobOut; onHidden: () => void }) {
  const { t } = useTranslation('jobs');
  const { t: common } = useTranslation();
  const format = useFormat();
  const locale = useLocale();
  const platform = usePlatform();
  const client = useQueryClient();
  const whenBadge = useWhenBadge();
  const budgetText = useBudgetText();
  const hide = useHideJob();
  const tree = useCategories(locale).data ?? [];
  const category = findCategory(tree, job.category_id)?.name ?? null;
  const owner = job.viewer_role === 'owner';
  // сохранить и скрыть может только вошедший: гостю кнопок нет
  const performer = !owner && getSession() !== null;
  const saved = useSavedJobs();
  const toggleSaved = useToggleSavedJob();
  const isSaved = savedJobIds(saved.data).has(job.id);
  const saveError = toggleSaved.error;
  const saveFailure = !toggleSaved.isError
    ? null
    : saveError instanceof ApiError && saveError.code === SAVED_FULL
      ? t('job.savedFull', { limit: Number(saveError.problem['limit'] ?? MAX_SAVED) })
      : t('job.saveError');
  const budget = budgetText(job, { unit: false });
  const when = whenBadge(job, true);
  const languages = job.languages.filter((code): code is LanguageName =>
    (LANGUAGE_NAMES as readonly string[]).includes(code),
  );
  const descriptionId = useId();
  const whereId = useId();

  return (
    <section className="flex flex-col gap-3 px-4 pt-3 pb-6">
      {owner && (
        <Banner tone="info" icon="eye">
          {job.status === 'published'
            ? t('job.ownerPublished')
            : t('job.ownerStatus', { status: common(`status.job.${job.status}`) })}
        </Banner>
      )}
      {saveFailure && (
        <Banner tone="danger" role="alert">
          {saveFailure}
        </Banner>
      )}
      {job.photos.length > 0 && <Photos job={job} />}
      <Card as="section">
        <div className="flex flex-wrap gap-1.5">
          <Badge tone={when.tone} icon={when.icon}>
            {when.label}
          </Badge>
          {category && <Badge>{category}</Badge>}
        </div>
        <div className="flex items-start justify-between gap-2">
          <Heading variant="h2" as="h1" className="pt-2">
            {job.title}
          </Heading>
          {performer && saved.data && (
            <IconButton
              plain
              icon="heart"
              label={isSaved ? t('job.unsave') : t('job.save')}
              active={isSaved}
              aria-pressed={isSaved}
              className="-mt-1 -mr-2"
              onClick={() => {
                platform.haptics.selection();
                toggleSaved.mutate({ card: jobCardOf(job), on: !isSaved });
              }}
            />
          )}
        </div>
        <div className="flex items-baseline justify-between gap-3">
          <span className="flex min-w-0 items-baseline gap-2">
            {budget ? (
              <>
                <Price large>{budget}</Price>
                <Text as="span" variant="cap">
                  {job.budget_unit === 'work'
                    ? t('job.unitWork')
                    : common(`unit.${job.budget_unit}`)}
                </Text>
              </>
            ) : (
              <span className="text-price-lg text-text2">{t('card.negotiable')}</span>
            )}
          </span>
          {job.published_at && (
            <Text as="span" variant="cap" className="shrink-0">
              {format.relative(new Date(job.published_at))}
            </Text>
          )}
        </div>
        <hr className="m-0 h-px border-0 bg-line" />
        <Slots taken={job.responses_count} total={job.max_responses} />
      </Card>
      <Card as="section" tight aria-labelledby={descriptionId}>
        <Heading variant="h3" as="h2" id={descriptionId}>
          {t('job.description')}
        </Heading>
        <Text className="whitespace-pre-line">{job.description}</Text>
        {languages.length > 0 && (
          <p className="m-0 flex items-center gap-1.5 text-cap text-text2">
            <Icon name="languages" size={16} className="shrink-0" />
            {t('job.languages', {
              languages: languages.map((code) => t(`job.langs.${code}`)).join(', '),
            })}
          </p>
        )}
      </Card>
      <Where job={job} labelledBy={whereId} />
      {job.client && (
        <Client
          name={job.client.display_name}
          since={job.client.member_since}
          jobs={job.client.jobs_count}
          phoneVerified={job.client.phone_verified}
        />
      )}
      {performer && (
        <>
          {hide.isError && (
            <Banner tone="danger" role="alert">
              {t('job.hideError')}
            </Banner>
          )}
          <Button
            variant="outline"
            icon="x"
            full
            disabled={hide.isPending}
            aria-busy={hide.isPending}
            onClick={() =>
              hide.mutate(job.id, {
                onSuccess: () => {
                  client.removeQueries({ queryKey: jobQueryKey(job.id) });
                  onHidden();
                },
              })
            }
          >
            {t('job.hide')}
          </Button>
        </>
      )}
    </section>
  );
}

/** Фото заявки сеткой в две колонки; одно — на всю ширину. */
function Photos({ job }: { job: JobOut }) {
  const { t } = useTranslation('jobs');
  const total = job.photos.length;
  return (
    <div
      role="group"
      aria-label={t('job.photos', { count: total })}
      className={total === 1 ? 'grid grid-cols-1' : 'grid grid-cols-2 gap-2'}
    >
      {job.photos.map((photo, index) => (
        <Photo
          key={photo.url}
          src={photo.url}
          placeholder={photo.placeholder}
          alt={t('job.photo', { number: index + 1, total })}
          sizes={total === 1 ? '100vw' : '50vw'}
          className={total === 1 ? 'h-45 w-full' : 'h-25 w-full'}
        />
      ))}
    </div>
  );
}

/** «Откликов 3 из 5 · Осталось 2 места» и полоски мест на всю ширину. */
function Slots({ taken, total }: { taken: number; total: number }) {
  const { t: common } = useTranslation();
  const shown = Math.min(Math.max(taken, 0), total);
  const left = total - shown;
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between gap-3 text-sm font-semibold">
        <span>{capitalized(common('count.responsesOf', { count: shown, total }))}</span>
        <span className={left > 0 ? 'text-accent-soft-ink' : 'text-text2'}>
          {left > 0
            ? capitalized(common('count.slotsLeft', { count: left }))
            : common('count.full')}
        </span>
      </div>
      <span
        aria-hidden="true"
        className="grid gap-1"
        style={{ gridTemplateColumns: `repeat(${total}, minmax(0, 1fr))` }}
      >
        {Array.from({ length: total }, (_, index) => (
          <i
            key={index}
            className={
              index < shown ? 'h-1.5 rounded-full bg-accent' : 'h-1.5 rounded-full bg-line'
            }
          />
        ))}
      </span>
    </div>
  );
}

/** «Где»: район на схеме и «≈ 1,2 км от вас», если лента знала точку исполнителя. */
function Where({ job, labelledBy }: { job: JobOut; labelledBy: string }) {
  const { t } = useTranslation('jobs');
  const format = useFormat();
  const locale = useLocale();
  const search: JobSearch = useSearch({ strict: false });
  const districts = selectableDistricts(useDistricts(job.city_id, locale).data ?? [], locale);
  const city = useCities(locale).data?.find((item) => item.id === job.city_id);
  const place =
    districts.find((district) => district.id === job.district_id)?.name ?? city?.name ?? null;
  const distance =
    search.lat !== undefined && search.lon !== undefined && job.point_public
      ? format.distance(distanceMeters({ lat: search.lat, lon: search.lon }, job.point_public))
      : null;
  return (
    <Card as="section" aria-labelledby={labelledBy}>
      <div className="flex items-center justify-between gap-3">
        <Heading variant="h3" as="h2" id={labelledBy}>
          {t('job.where')}
        </Heading>
        {place && (
          <Text as="span" variant="cap">
            {distance ? t('job.placeDistance', { place, distance }) : place}
          </Text>
        )}
      </div>
      {place && <MapPreview label={place} description={t('job.map', { place })} />}
      <Banner tone="info" icon="lock">
        {t('job.addressPrivate')}
      </Banner>
    </Card>
  );
}

function Client({
  name,
  since,
  jobs,
  phoneVerified,
}: {
  name: string;
  since: string;
  jobs: number;
  phoneVerified: boolean;
}) {
  const { t } = useTranslation('jobs');
  const memberFor = useMemberFor();
  return (
    <Card as="section" aria-label={t('job.client.label')}>
      <div className="flex items-start gap-3">
        <Avatar name={name} />
        <div className="flex min-w-0 grow flex-col gap-1">
          <span className="text-title">{name}</span>
          <Text as="span" variant="cap">
            {`${memberFor(since)} · ${t('job.client.jobs', { count: jobs })}`}
          </Text>
          {phoneVerified && (
            <Badge tone="info" icon="shield" className="self-start">
              {t('job.client.phoneVerified')}
            </Badge>
          )}
        </div>
      </div>
    </Card>
  );
}

function Unavailable({ onFeed }: { onFeed: () => void }) {
  const { t } = useTranslation('jobs');
  return (
    <section className="px-4 pt-6">
      <EmptyState
        as="h1"
        icon="jobs"
        title={t('job.unavailableTitle')}
        action={
          <Button variant="secondary" onClick={onFeed}>
            {t('job.toFeed')}
          </Button>
        }
      >
        {t('job.unavailableText')}
      </EmptyState>
    </section>
  );
}

function Loading() {
  return (
    <section className="flex flex-col gap-3 px-4 pt-3 pb-6" aria-busy="true">
      <Skeleton radius="card" className="h-44 w-full" />
      <Skeleton radius="card" className="h-28 w-full" />
      <Skeleton radius="card" className="h-44 w-full" />
    </section>
  );
}
