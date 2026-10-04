// Работа портфолио (DEVELOPMENT_PLAN 2.11, из S37): фото или ролик крупно, подпись, место в
// портфолио («Раньше» / «Позже» вместо перетаскивания с артборда S37) и «Убрать из портфолио»
// после подтверждения. «Сохранить» (MainButton) — PATCH подписи и PUT порядка, только изменённое.
// Работа на проверке (6.7) — баннер «клиенты увидят её после проверки»; скрытая модератором —
// баннер с причиной в уведомлении. Новая подпись снова уходит на проверку.
import type { PortfolioOut, WorkOut } from '@sosed/api-client';
import { specialistsCaptionMyWork, specialistsReorderMyPortfolio } from '@sosed/api-client';
import {
  hiddenByModerator,
  onReview,
  processing,
  useMyPortfolio,
  useMyProfile,
} from '@sosed/hooks';
import { useTranslation } from '@sosed/i18n';
import { useBackButton, usePlatform } from '@sosed/platform';
import {
  Banner,
  Button,
  Field,
  Heading,
  Icon,
  Input,
  Photo,
  Text,
  VideoPlayer,
  cx,
} from '@sosed/ui-web';
import { useMutation } from '@tanstack/react-query';
import { useParams, useRouter } from '@tanstack/react-router';
import { useEffect, useId, useState } from 'react';

import { LoadState } from '../shared/LoadState.tsx';
import { SaveError } from '../shared/SaveError.tsx';
import { useStepButton } from '../shared/flow.ts';
import { ACCOUNT_PATH, CABINET_PATHS } from '../shared/paths.ts';
import {
  MAX_CAPTION,
  photoVariants,
  usePortfolioCache,
  useRemoveWork,
} from '../shared/portfolio.ts';

export function WorkScreen() {
  const { t } = useTranslation('specialist');
  const router = useRouter();
  const params: { itemId?: string } = useParams({ strict: false });
  const profile = useMyProfile();
  const portfolio = useMyPortfolio({ enabled: Boolean(profile.data) });
  const back = () => {
    if (router.history.canGoBack()) router.history.back();
    else void router.navigate({ to: CABINET_PATHS.portfolio, replace: true });
  };
  useBackButton(back);
  const work = portfolio.data?.items.find((item) => item.id === params.itemId);
  useEffect(() => {
    if (profile.data === null) void router.navigate({ to: ACCOUNT_PATH, replace: true });
    // работу убрали или её нет — к портфолио
    else if (portfolio.data && !work) {
      void router.navigate({ to: CABINET_PATHS.portfolio, replace: true });
    }
  }, [portfolio.data, profile.data, router, work]);

  if (portfolio.data && work) {
    return <WorkForm portfolio={portfolio.data} work={work} onDone={back} />;
  }
  const loads = [profile, portfolio];
  const failed = loads.find((load) => load.isError);
  return (
    <section className="flex flex-col gap-3 px-4 pt-3 pb-6">
      <Heading variant="h2" as="h1">
        {t('work.title')}
      </Heading>
      <LoadState
        shape="work"
        error={failed ? failed.error : null}
        onRetry={() => {
          for (const load of loads) if (load.isError) void load.refetch();
        }}
        retrying={loads.some((load) => load.isFetching)}
      />
    </section>
  );
}

/** Порядок работ (id), где работа `id` стоит на месте `place` (с нуля). */
function placed(items: readonly WorkOut[], id: string, place: number): string[] {
  const others = items.map((item) => item.id).filter((other) => other !== id);
  return [...others.slice(0, place), id, ...others.slice(place)];
}

function WorkForm({
  portfolio,
  work,
  onDone,
}: {
  portfolio: PortfolioOut;
  work: WorkOut;
  onDone: () => void;
}) {
  const { t } = useTranslation('specialist');
  const platform = usePlatform();
  const cache = usePortfolioCache();
  const placeId = useId();
  const count = portfolio.items.length;
  const current = portfolio.items.findIndex((item) => item.id === work.id);
  const [caption, setCaption] = useState(work.caption ?? '');
  const [place, setPlace] = useState(current);
  const title = work.caption ?? t('portfolio.work', { number: current + 1 });

  const save = useMutation({
    mutationFn: async () => {
      // пробелы сервер схлопывает так же: «ничего не изменилось» — без запроса
      const text = caption.split(/\s+/).filter(Boolean).join(' ');
      let items = portfolio.items;
      if (text !== (work.caption ?? '')) {
        const changed = await specialistsCaptionMyWork(work.id, { caption: text || null });
        items = items.map((item) => (item.id === changed.id ? changed : item));
        await cache((list) => list.map((item) => (item.id === changed.id ? changed : item)));
      }
      if (place !== items.findIndex((item) => item.id === work.id)) {
        const reordered = await specialistsReorderMyPortfolio({
          item_ids: placed(items, work.id, place),
        });
        await cache(() => reordered.items);
      }
    },
    onSuccess: () => {
      platform.haptics.notification('success');
      onDone();
    },
  });
  const remove = useRemoveWork(onDone);

  useStepButton({
    text: t('work.save'),
    onClick: () => {
      if (!save.isPending && !remove.isPending) save.mutate();
    },
    loading: save.isPending,
  });

  const move = (step: -1 | 1) => {
    platform.haptics.selection();
    setPlace(Math.min(Math.max(place + step, 0), count - 1));
  };
  const confirmRemove = async () => {
    if (await platform.confirm(t('work.deleteConfirm'))) remove.mutate(work);
  };

  return (
    <section className="flex flex-col gap-3.5 px-4 pt-3 pb-6">
      <Heading variant="h2" as="h1">
        {t('work.title')}
      </Heading>
      <WorkMedia work={work} title={title} />
      {onReview(work) && <Banner tone="info">{t('work.review')}</Banner>}
      {hiddenByModerator(work) && <Banner tone="danger">{t('work.hidden')}</Banner>}
      <Field
        label={t('work.caption')}
        hint={t('work.captionHint', { count: caption.length, max: MAX_CAPTION })}
      >
        <Input
          value={caption}
          maxLength={MAX_CAPTION}
          placeholder={t('work.captionPlaceholder')}
          onChange={(event) => setCaption(event.target.value)}
        />
      </Field>
      {count > 1 && (
        <section aria-labelledby={placeId} className="flex flex-col gap-1.5">
          <h2 id={placeId} className="m-0 text-sm font-semibold">
            {t('work.order')}
          </h2>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              icon="chev-left"
              disabled={place === 0}
              onClick={() => move(-1)}
            >
              {t('work.earlier')}
            </Button>
            <Text as="span" variant="sm" className="flex-1 text-center tabular-nums">
              <output aria-live="polite">{t('work.place', { place: place + 1, count })}</output>
            </Text>
            {/* стрелка — после текста: зеркально «Раньше» */}
            <Button
              variant="outline"
              size="sm"
              disabled={place === count - 1}
              onClick={() => move(1)}
            >
              {t('work.later')}
              <Icon name="chev-right" size={16} />
            </Button>
          </div>
        </section>
      )}
      <Button
        variant="danger"
        full
        icon="trash"
        disabled={remove.isPending}
        aria-busy={remove.isPending}
        onClick={() => void confirmRemove()}
        className={cx(remove.isPending && 'opacity-70')}
      >
        {t('work.delete')}
      </Button>
      {(save.isError || remove.isError) && <SaveError error={save.error ?? remove.error} />}
    </section>
  );
}

/** Фото крупно; ролик — плеером с постером, пока не обработан — постер или штриховка. */
function WorkMedia({ work, title }: { work: WorkOut; title: string }) {
  const { t } = useTranslation('specialist');
  const media = work.media;
  const variants = photoVariants(media);
  const poster = media?.variants.at(-1);
  if (work.kind === 'video' && media?.video_url) {
    return (
      <VideoPlayer
        src={media.video_url}
        poster={poster?.url}
        width={poster?.width}
        height={poster?.height}
        label={t('portfolio.video', { title })}
      />
    );
  }
  return (
    <Photo
      variants={variants}
      placeholder={media?.placeholder}
      sizes="100vw"
      alt={media && processing(work) ? t('portfolio.processing') : title}
      video={work.kind === 'video'}
      className="aspect-[4/3] w-full"
    />
  );
}
