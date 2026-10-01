// S37 Портфолио (DEVELOPMENT_PLAN 2.11): работы плитками по порядку; «Фото или видео» — загрузка с
// прогрессом прямо в сетке. Загруженный файл сразу становится работой в конце портфолио, а пока
// сервер его обрабатывает, плитка показывает превью с устройства. Нажатие на работу — подпись,
// место и удаление на экране работы: перетаскивание с артборда в WebView Telegram спорит со
// свайпом закрытия. Лимиты — 60 фото и 6 роликов (из ответа сервера): лишние файлы не грузятся,
// баннер говорит, сколько. Файл, не прошедший обработку, — плитка «Не подходит» с «Убрать».
// Альбомы — v1.
import type { PortfolioOut, WorkOut } from '@sosed/api-client';
import type { UploadItem } from '@sosed/hooks';
import {
  PORTFOLIO_ACCEPT,
  broken,
  portfolioRoom,
  processing,
  useMyPortfolio,
  useMyProfile,
  usePortfolioUploads,
} from '@sosed/hooks';
import { useTranslation } from '@sosed/i18n';
import { useBackButton, usePlatform } from '@sosed/platform';
import { AddTile, Banner, Heading, Photo, Text, UploadTile, cx } from '@sosed/ui-web';
import { useRouter } from '@tanstack/react-router';
import type { MouseEvent } from 'react';
import { useEffect, useState } from 'react';

import { LoadState } from '../shared/LoadState.tsx';
import { SaveError } from '../shared/SaveError.tsx';
import { ACCOUNT_PATH, CABINET_PATHS } from '../shared/paths.ts';
import { photoVariants, useRemoveWork } from '../shared/portfolio.ts';
import { mediaTransport } from '../shared/uploads.ts';

/** Плитка сетки: квадрат в треть ширины, как .ph 114 px артборда на 390 px. */
const TILE = 'aspect-square w-full';

export function PortfolioScreen() {
  const { t } = useTranslation('specialist');
  const router = useRouter();
  const profile = useMyProfile();
  const portfolio = useMyPortfolio({ enabled: Boolean(profile.data) });
  useBackButton(() => {
    if (router.history.canGoBack()) router.history.back();
    else void router.navigate({ to: CABINET_PATHS.home, replace: true });
  });
  useEffect(() => {
    if (profile.data === null) void router.navigate({ to: ACCOUNT_PATH, replace: true });
  }, [profile.data, router]);

  if (profile.data && portfolio.data) return <Portfolio portfolio={portfolio.data} />;
  const loads = [profile, portfolio];
  const failed = loads.find((load) => load.isError);
  return (
    <section className="flex flex-col gap-3.5 px-4 pt-3 pb-6">
      <Heading variant="h2" as="h1">
        {t('portfolio.title')}
      </Heading>
      <LoadState
        error={failed ? failed.error : null}
        onRetry={() => {
          for (const load of loads) if (load.isError) void load.refetch();
        }}
        retrying={loads.some((load) => load.isFetching)}
      />
    </section>
  );
}

function Portfolio({ portfolio }: { portfolio: PortfolioOut }) {
  const { t } = useTranslation('specialist');
  const { t: common } = useTranslation();
  const platform = usePlatform();
  const uploads = usePortfolioUploads(portfolio, { transport: mediaTransport });
  const remove = useRemoveWork();
  // сколько файлов последнего выбора не поместилось в лимиты
  const [skipped, setSkipped] = useState(0);
  const { items: works, limits } = portfolio;
  const room = portfolioRoom(
    works,
    limits,
    uploads.items.map((item) => item.file),
  );

  const add = (files: File[]) => {
    const left = uploads.add(files);
    setSkipped(left);
    if (left > 0) platform.haptics.notification('warning');
    else platform.haptics.selection();
  };

  return (
    <section className="flex flex-col gap-3.5 px-4 pt-3 pb-6">
      <div className="flex items-center justify-between gap-3">
        <Heading variant="h2" as="h1">
          {t('portfolio.title')}
        </Heading>
        {works.length > 0 && (
          <Text as="span" variant="cap">
            {t('portfolio.count', { count: works.length })}
          </Text>
        )}
      </div>
      <Text variant="cap">
        {t('portfolio.rules', { photos: limits.image, videos: limits.video })}
      </Text>
      <Text variant="cap">{t(works.length > 0 ? 'portfolio.hint' : 'portfolio.empty')}</Text>
      {skipped > 0 && (
        <Banner tone="info">
          {t('portfolio.skipped', { count: skipped, photos: limits.image, videos: limits.video })}
        </Banner>
      )}
      <div className="grid grid-cols-3 gap-2">
        <AddTile
          label={common('photo.addMedia')}
          accept={PORTFOLIO_ACCEPT}
          multiple
          disabled={room.image + room.video === 0}
          onFiles={add}
          className={TILE}
        />
        {uploads.items.map((item) => (
          <UploadingWork
            key={item.key}
            item={item}
            onRetry={() => uploads.retry(item.key)}
            onRemove={() => uploads.remove(item.key)}
          />
        ))}
        {works.map((work, index) => (
          <WorkTile
            key={work.id}
            work={work}
            number={index + 1}
            preview={work.media ? (uploads.previews.get(work.media.id) ?? null) : null}
            onRemove={() => remove.mutate(work)}
          />
        ))}
      </div>
      {remove.isError && <SaveError error={remove.error} />}
    </section>
  );
}

/** Файл, который ещё не стал работой: грузится, прикрепляется или упал. */
function UploadingWork({
  item,
  onRetry,
  onRemove,
}: {
  item: UploadItem;
  onRetry: () => void;
  onRemove: () => void;
}) {
  const { t: common } = useTranslation();
  if (item.status === 'failed') {
    return (
      <UploadTile
        state="failed"
        label={common(item.retryable ? 'photo.uploadFailed' : 'photo.rejected')}
        onRetry={item.retryable ? onRetry : undefined}
        retryLabel={common('action.retry')}
        onRemove={onRemove}
        removeLabel={common('photo.remove')}
        className={TILE}
      />
    );
  }
  // загружен, но ещё прикрепляется — тоже «загрузка»: работы пока нет
  const progress = item.status === 'uploaded' ? 1 : item.progress;
  return (
    <UploadTile
      state="uploading"
      progress={progress}
      label={common('photo.uploading', { percent: Math.round(progress * 100) })}
      className={TILE}
    />
  );
}

function WorkTile({
  work,
  number,
  preview,
  onRemove,
}: {
  work: WorkOut;
  /** Номер по порядку — подпись работы без своей. */
  number: number;
  /** Превью с устройства, пока сервер обрабатывает только что загруженный файл. */
  preview: Blob | null;
  onRemove: () => void;
}) {
  const { t } = useTranslation('specialist');
  const { t: common } = useTranslation();
  const router = useRouter();
  const title = work.caption ?? t('portfolio.work', { number });
  if (broken(work)) {
    return (
      <UploadTile
        state="failed"
        label={common('photo.rejected')}
        retryLabel={common('action.retry')}
        onRemove={onRemove}
        removeLabel={common('photo.remove')}
        className={TILE}
      />
    );
  }
  const waiting = processing(work);
  const video = work.kind === 'video';
  const open = (event: MouseEvent<HTMLElement>) => {
    event.preventDefault();
    void router.navigate({ to: CABINET_PATHS.work, params: { itemId: work.id } });
  };
  return (
    <a
      href={router.history.createHref(`${CABINET_PATHS.portfolio}/${work.id}`)}
      onClick={open}
      aria-label={video ? t('portfolio.video', { title }) : title}
      className={cx(
        'block rounded-photo outline-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent',
        TILE,
      )}
    >
      <Photo
        variants={photoVariants(work.media)}
        placeholder={work.media?.placeholder}
        file={waiting ? preview : null}
        sizes="33vw"
        alt={waiting && !preview ? t('portfolio.processing') : title}
        video={video}
        className="size-full"
      />
    </a>
  );
}
