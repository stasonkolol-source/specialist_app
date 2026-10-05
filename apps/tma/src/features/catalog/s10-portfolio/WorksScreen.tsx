// S10 Просмотр работ (DEVELOPMENT_PLAN 4.5): работа крупно на тёмном фоне при любой теме — и
// приложение, и шапка Telegram. Листают свайпом, стрелками на фото и с клавиатуры; внизу —
// миниатюры по четыре и «+N» к следующим. Открытая работа — в адресе (`?work=`), листание
// заменяет запись истории: «Назад» и «×» закрывают просмотр, а не листают назад. Вертикальные
// свайпы Telegram выключены: жест листания не сворачивает Mini App. «Поделиться» (7.4) — справа от
// счётчика: ссылка на профиль специалиста (у работы своего кода deep link нет). MainButton
// «Написать …» — 5.6 и 6.4. Кадр не выше экрана за вычетом шапки, подписи и миниатюр (FRAME): на
// 375×667 миниатюры и «+N» видны без прокрутки, на высоких экранах кадр по-прежнему 5:6.
import type { CardWorkOut } from '@sosed/api-client';
import { cardVariants, isUnavailable, largestVariant, useSpecialistWorks } from '@sosed/hooks';
import { useTranslation } from '@sosed/i18n';
import { useBackButton, useColorSchemeOverride, useInsets, usePlatform } from '@sosed/platform';
import { EmptyState, Heading, IconButton, Photo, Skeleton, VideoPlayer, cx } from '@sosed/ui-web';
import { useParams, useRouter, useSearch } from '@tanstack/react-router';
import type { CSSProperties, PointerEvent } from 'react';
import { useEffect, useEffectEvent, useRef } from 'react';

import { LoadError } from '../shared/LoadError.tsx';
import { Unavailable } from '../shared/Unavailable.tsx';
import type { PortfolioSearch } from '../shared/paths.ts';
import { CARD_PATHS } from '../shared/paths.ts';
import { useProfileShare } from '../shared/share.tsx';

/** Миниатюр в ряду; дальше — «+N». */
const THUMBS = 4;
/** Свайп короче — не листание (дрогнул палец). */
const SWIPE_PX = 48;
/** Кадр работы: 5:6 во всю ширину, но не выше экрана без верхнего отступа Telegram (`--tg-top`) и
 *  232 px — панель 44, зазоры 3×16, подпись 22, миниатюры 56, низ 24 и запас. `fit="contain"` —
 *  фото в укороченном кадре остаётся целым. */
const FRAME = 'aspect-5/6 w-full max-h-[calc(100dvh-var(--tg-top,0px)-232px)]';

export function WorksScreen() {
  const { t } = useTranslation('catalog');
  const { profileId } = useParams({ strict: false }) as { profileId: string };
  const search: PortfolioSearch = useSearch({ strict: false });
  const router = useRouter();
  const platform = usePlatform();
  // верхний отступ оболочки (полноэкранный Telegram: safe area и его кнопки) — для высоты кадра
  const top = useInsets().top;
  const works = useSpecialistWorks(profileId);
  const sharing = useProfileShare(profileId);
  useColorSchemeOverride('dark');
  useEffect(() => {
    platform.setVerticalSwipes(false);
    return () => platform.setVerticalSwipes(true);
  }, [platform]);
  const close = () => {
    if (router.history.canGoBack()) router.history.back();
    else void router.navigate({ to: CARD_PATHS.profile, params: { profileId }, replace: true });
  };
  useBackButton(close);

  let content;
  if (isUnavailable(works.error)) {
    content = <Unavailable />;
  } else if (works.data) {
    content =
      works.data.items.length === 0 ? (
        <EmptyState as="h2" icon="image" title={t('portfolio.empty')} />
      ) : (
        <Viewer
          items={works.data.items}
          current={search.work}
          onOpen={(work) =>
            void router.navigate({
              to: CARD_PATHS.portfolio,
              params: { profileId },
              search: { work },
              replace: true,
            })
          }
          onClose={close}
          onShare={sharing.share}
          sharing={sharing.pending}
        />
      );
  } else if (works.isError) {
    content = (
      <LoadError
        error={works.error}
        onRetry={() => void works.refetch()}
        retrying={works.isRefetching}
      />
    );
  } else {
    content = <Loading onClose={close} />;
  }
  return (
    <section
      className="flex flex-col gap-4 pt-1.5 pb-6"
      style={{ '--tg-top': `${top}px` } as CSSProperties}
    >
      <Heading variant="h2" as="h1" className="sr-only">
        {t('portfolio.title')}
      </Heading>
      {content}
      {sharing.notice}
    </section>
  );
}

/** Фото в кэш браузера тем же выбором варианта, что у Photo во всю ширину (`sizes="100vw"`). */
function preloadPhoto(variants: readonly { url: string; width: number }[]) {
  if (variants.length === 0) return;
  const image = new Image();
  image.decoding = 'async';
  // sizes — до srcset: иначе браузер успел бы выбрать вариант без него
  image.sizes = '100vw';
  image.srcset = variants.map((variant) => `${variant.url} ${variant.width}w`).join(', ');
}

/** Просмотрщик до ответа: «Закрыть» уже работает, кадр и превью — скелетоном (фон экрана тёмный,
 *  фигуры — цвета поверхности). */
function Loading({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation('catalog');
  return (
    <div aria-busy="true" className="flex flex-col gap-4">
      <div className="flex items-center justify-between px-2">
        <IconButton plain icon="x" label={t('portfolio.close')} onClick={onClose} />
        <Skeleton screen className="h-4 w-12" />
        <span className="size-11" aria-hidden="true" />
      </div>
      <Skeleton screen radius="panel" className={FRAME} />
      <div className="flex gap-2 px-4">
        {[0, 1, 2, 3].map((thumb) => (
          <Skeleton key={thumb} screen radius="panel" className="size-14" />
        ))}
      </div>
    </div>
  );
}

function Viewer({
  items,
  current,
  onOpen,
  onClose,
  onShare,
  sharing,
}: {
  items: CardWorkOut[];
  current: string | undefined;
  onOpen: (workId: string) => void;
  onClose: () => void;
  onShare: () => void;
  sharing: boolean;
}) {
  const { t } = useTranslation('catalog');
  const common = useTranslation().t;
  // неизвестная работа (удалили, пока открывали ссылку) — первая
  const index = Math.max(
    0,
    items.findIndex((work) => work.id === current),
  );
  const work = items[index] as CardWorkOut;
  const count = items.length;
  const go = (to: number) => {
    const target = items[to];
    if (target) onOpen(target.id);
  };
  const previous = index > 0 ? () => go(index - 1) : undefined;
  const next = index < count - 1 ? () => go(index + 1) : undefined;
  const title = work.caption ?? t('profile.work', { number: index + 1 });

  // клавиатура (браузерная оболочка, настольный Telegram)
  const onKey = useEffectEvent((event: KeyboardEvent) => {
    if (event.key === 'ArrowLeft') previous?.();
    if (event.key === 'ArrowRight') next?.();
  });
  useEffect(() => {
    const listener = (event: KeyboardEvent) => onKey(event);
    window.addEventListener('keydown', listener);
    return () => window.removeEventListener('keydown', listener);
  }, []);

  const start = useRef<{ x: number; y: number } | null>(null);
  const onPointerDown = (event: PointerEvent) => {
    start.current = { x: event.clientX, y: event.clientY };
  };
  const onPointerUp = (event: PointerEvent) => {
    const from = start.current;
    start.current = null;
    if (!from) return;
    const dx = event.clientX - from.x;
    if (Math.abs(dx) < SWIPE_PX || Math.abs(dx) < Math.abs(event.clientY - from.y)) return;
    (dx < 0 ? next : previous)?.();
  };

  // соседние работы — заранее: листание не ждёт сети
  useEffect(() => {
    for (const near of [items[index - 1], items[index + 1]]) {
      if (near && near.kind !== 'video') preloadPhoto(cardVariants(near.photo));
    }
  }, [index, items]);

  const poster = largestVariant(work.photo);
  return (
    <>
      <div className="flex items-center justify-between px-2">
        <IconButton plain icon="x" label={t('portfolio.close')} onClick={onClose} />
        <span className="font-semibold tabular-nums" aria-live="polite">
          {t('portfolio.position', { number: index + 1, count })}
        </span>
        <IconButton
          plain
          icon="share"
          label={common('share.work')}
          aria-busy={sharing || undefined}
          onClick={onShare}
        />
      </div>
      <figure className="m-0 flex flex-col gap-4">
        <div
          className="relative touch-pan-y"
          onPointerDown={onPointerDown}
          onPointerUp={onPointerUp}
          onPointerCancel={() => (start.current = null)}
        >
          {work.kind === 'video' && work.photo.video_url ? (
            <VideoPlayer
              key={work.id}
              src={work.photo.video_url}
              poster={poster?.url}
              label={t('profile.video', { title })}
              className={FRAME}
            />
          ) : (
            <Photo
              variants={cardVariants(work.photo)}
              placeholder={work.photo.placeholder}
              sizes="100vw"
              alt={title}
              fit="contain"
              priority
              className={FRAME}
            />
          )}
          {previous && (
            <IconButton
              icon="chev-left"
              label={t('portfolio.previous')}
              onClick={previous}
              className="absolute top-1/2 left-3 -translate-y-1/2"
            />
          )}
          {next && (
            <IconButton
              icon="chev-right"
              label={t('portfolio.next')}
              onClick={next}
              className="absolute top-1/2 right-3 -translate-y-1/2"
            />
          )}
        </div>
        {work.caption && (
          <figcaption className="px-4">
            <span className="text-h3">{work.caption}</span>
          </figcaption>
        )}
      </figure>
      {count > 1 && <Thumbs items={items} index={index} onOpen={go} />}
    </>
  );
}

/** Миниатюры по четыре вокруг открытой работы; «+N» открывает первую из следующих. */
function Thumbs({
  items,
  index,
  onOpen,
}: {
  items: CardWorkOut[];
  index: number;
  onOpen: (index: number) => void;
}) {
  const { t } = useTranslation('catalog');
  const count = items.length;
  const first = Math.floor(index / THUMBS) * THUMBS;
  const shown = items.slice(first, first + THUMBS);
  const rest = count - first - shown.length;
  const thumb = 'size-14 shrink-0 overflow-hidden rounded-photo border-0 bg-transparent p-0';
  // открытая — с акцентной обводкой, как на артборде; у остальных обводка — только фокус
  const ring = (open: boolean) =>
    open
      ? 'outline-2 outline-offset-2 outline-accent'
      : 'outline-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent';
  return (
    <div role="group" aria-label={t('portfolio.others')} className="flex gap-2 px-4">
      {shown.map((work, offset) => {
        const position = first + offset;
        const open = position === index;
        return (
          <button
            key={work.id}
            type="button"
            aria-label={t(open ? 'portfolio.thumbCurrent' : 'portfolio.thumb', {
              number: position + 1,
              count,
            })}
            aria-current={open || undefined}
            onClick={() => onOpen(position)}
            className={cx(thumb, ring(open))}
          >
            <Photo
              variants={cardVariants(work.photo)}
              placeholder={work.photo.placeholder}
              sizes="56px"
              alt=""
              video={work.kind === 'video'}
              className="size-full"
            />
          </button>
        );
      })}
      {rest > 0 && (
        <button
          type="button"
          aria-label={t('portfolio.more', { count: rest })}
          onClick={() => onOpen(first + THUMBS)}
          className={cx(
            thumb,
            ring(false),
            'ph-stripes flex items-center justify-center bg-bg2 font-semibold text-text',
          )}
        >
          <span aria-hidden="true">{t('portfolio.moreShort', { count: rest })}</span>
        </button>
      )}
    </div>
  );
}
