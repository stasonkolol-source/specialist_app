// Портфолио S37 (DEVELOPMENT_PLAN 2.11): какие из выбранных файлов поместятся, загрузка работ и их
// прикрепление. Лимиты — у сервера (60 фото и 6 роликов, приходят в ответе), здесь — чтобы не
// начинать загрузку, которую сервер всё равно не примет. Ролики — mp4 и mov, остальное — фото.
// - Загруженный файл сразу становится работой: POST /me/profile/portfolio с Idempotency-Key по id
//   файла — повтор после потерянного ответа вернёт ту же работу. Обработку файла (2.2) ждёт уже
//   портфолио: пока файлы обрабатываются, оно перечитывается, а плитка показывает превью.
// - Не прикрепилось (сеть, лимит) — плитка с ошибкой: «Повторить» прикрепляет снова, «Убрать»
//   удаляет файл. Ответ мог потеряться, а работа — появиться: перед удалением портфолио
//   перечитывается, и файл работы не удаляется.
// - Опрос портфолио, начатый до прикрепления, отменяется: его ответ затёр бы новую работу.
import type { PortfolioLimitsOut, PortfolioOut, WorkKind, WorkOut } from '@sosed/api-client';
import {
  ApiError,
  getSpecialistsGetMyPortfolioQueryKey,
  getSpecialistsGetMyPortfolioQueryOptions,
  specialistsAddMyWork,
  useSpecialistsGetMyPortfolio,
} from '@sosed/api-client';
import { useQueryClient } from '@tanstack/react-query';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import type { MediaApi, MediaTransport } from '../media/upload.ts';
import type { UploadItem } from '../media/useMediaUploads.ts';
import { useMediaUploads } from '../media/useMediaUploads.ts';
import { myProfileQueryKey } from './profile.ts';

export const PORTFOLIO_ACCEPT = 'image/*,video/mp4,video/quicktime';
/** Как часто перечитывать портфолио, пока файлы работ обрабатываются. */
export const PORTFOLIO_POLL_MS = 3000;
/** Файл обработан или отклонён: вариантов больше не прибавится. */
const SETTLED = new Set(['ready', 'failed', 'rejected']);

type File_ = Blob & { readonly name?: string };

export function workKindOf(file: { readonly type: string }): WorkKind {
  return file.type.startsWith('video/') ? 'video' : 'image';
}

/** Файл работы ещё обрабатывается: вариантов пока нет. */
export function processing(work: Pick<WorkOut, 'media'>): boolean {
  return work.media !== null && !SETTLED.has(work.media.status);
}

/** Файл работы не прошёл обработку: показать нечего, остаётся убрать работу. */
export function broken(work: Pick<WorkOut, 'media'>): boolean {
  return work.media?.status === 'failed' || work.media?.status === 'rejected';
}

export interface PortfolioRoom {
  image: number;
  video: number;
}

/** Сколько ещё работ каждого вида поместится: лимит минус готовые и те, что ещё грузятся. */
export function portfolioRoom(
  works: readonly Pick<WorkOut, 'kind'>[],
  limits: PortfolioLimitsOut,
  uploading: readonly { readonly type: string }[] = [],
): PortfolioRoom {
  const taken = (kind: WorkKind) =>
    works.filter((work) => work.kind === kind).length +
    uploading.filter((file) => workKindOf(file) === kind).length;
  return {
    image: Math.max(limits.image - taken('image'), 0),
    video: Math.max(limits.video - taken('video'), 0),
  };
}

/** Выбранные файлы, которые поместятся, по порядку; `skipped` — сколько не поместилось. */
export function fitFiles<F extends { readonly type: string }>(
  files: readonly F[],
  room: PortfolioRoom,
): { accepted: F[]; skipped: number } {
  const left = { ...room };
  const accepted = files.filter((file) => {
    const kind = workKindOf(file);
    if (left[kind] <= 0) return false;
    left[kind] -= 1;
    return true;
  });
  return { accepted, skipped: files.length - accepted.length };
}

/** Портфолио своего профиля; пока файлы работ обрабатываются — перечитывается. */
export function useMyPortfolio({ enabled = true }: { enabled?: boolean } = {}) {
  return useSpecialistsGetMyPortfolio({
    query: {
      enabled,
      refetchInterval: (query) =>
        query.state.data?.items.some(processing) ? PORTFOLIO_POLL_MS : false,
    },
  });
}

export interface PortfolioUploadsOptions {
  transport: MediaTransport;
  api?: MediaApi;
  sleep?: (ms: number) => Promise<void>;
}

export interface PortfolioUploads {
  /** Загрузки, которые ещё не стали работами: идут, упали или не прикрепились (`failed`). */
  readonly items: readonly UploadItem[];
  /** Загрузить то, что поместится в лимиты; вернёт, сколько файлов не поместилось. */
  add(files: readonly File_[]): number;
  /** Догрузить файл или снова прикрепить загруженный. */
  retry(key: string): void;
  /** Убрать: передача останавливается, файл удаляется — если он всё же не стал работой. */
  remove(key: string): void;
  /** Превью только что прикреплённых работ, пока сервер обрабатывает их файлы: по id файла. */
  readonly previews: ReadonlyMap<string, Blob>;
}

/** Повтор прикрепления поможет при сбое сети или сервера, но не при лимите или чужом файле. */
function attachRetryable(error: unknown): boolean {
  if (!(error instanceof ApiError)) return true;
  return error.status >= 500 || error.status === 429 || error.code === 'idempotency_in_progress';
}

/** Загрузка работ S37: файл — в хранилище, затем — работой в конец портфолио. */
export function usePortfolioUploads(
  portfolio: PortfolioOut | undefined,
  { transport, api, sleep }: PortfolioUploadsOptions,
): PortfolioUploads {
  const queryClient = useQueryClient();
  const uploads = useMediaUploads({
    purpose: 'portfolio',
    transport,
    ...(api ? { api } : {}),
    ...(sleep ? { sleep } : {}),
  });
  const { forget } = uploads;
  const [failures, setFailures] = useState<ReadonlyMap<string, unknown>>(new Map());
  const [previews, setPreviews] = useState<ReadonlyMap<string, Blob>>(new Map());
  const attaching = useRef(new Set<string>());

  const attach = useCallback(
    async (item: UploadItem) => {
      const { key, media, preview } = item;
      if (!media) return;
      attaching.current.add(key);
      try {
        const work = await specialistsAddMyWork(
          { media_id: media.id },
          { 'Idempotency-Key': `portfolio-${media.id}` },
        );
        const queryKey = getSpecialistsGetMyPortfolioQueryKey();
        await queryClient.cancelQueries({ queryKey });
        queryClient.setQueryData<PortfolioOut>(queryKey, (current) =>
          current && !current.items.some((other) => other.id === work.id)
            ? { ...current, items: [...current.items, work] }
            : current,
        );
        if (preview) setPreviews((current) => new Map(current).set(media.id, preview));
        forget(key);
        // полнота профиля считает работы — перечитываем
        void queryClient.invalidateQueries({ queryKey: myProfileQueryKey() });
      } catch (error) {
        setFailures((current) => new Map(current).set(key, error));
      } finally {
        attaching.current.delete(key);
      }
    },
    [forget, queryClient],
  );

  useEffect(() => {
    for (const item of uploads.items) {
      const ready = item.status === 'uploaded' && item.media !== null;
      if (ready && !attaching.current.has(item.key) && !failures.has(item.key)) void attach(item);
    }
  }, [attach, failures, uploads.items]);

  const items = useMemo(
    () =>
      uploads.items.map((item): UploadItem => {
        if (!failures.has(item.key)) return item;
        const error = failures.get(item.key);
        return { ...item, status: 'failed', error, retryable: attachRetryable(error) };
      }),
    [failures, uploads.items],
  );

  const drop = useCallback(
    (key: string) =>
      setFailures((current) => {
        if (!current.has(key)) return current;
        const next = new Map(current);
        next.delete(key);
        return next;
      }),
    [],
  );

  const { add: start, retry: resend, remove: discard } = uploads;
  const add = useCallback(
    (files: readonly File_[]) => {
      if (!portfolio) return files.length;
      const pending = uploads.items.map((item) => item.file);
      const room = portfolioRoom(portfolio.items, portfolio.limits, pending);
      const { accepted, skipped } = fitFiles(files, room);
      if (accepted.length > 0) start(accepted);
      return skipped;
    },
    [portfolio, start, uploads.items],
  );
  const retry = useCallback(
    (key: string) => {
      // не прикрепилось — забываем ошибку: эффект прикрепит снова
      if (failures.has(key)) drop(key);
      else resend(key);
    },
    [drop, failures, resend],
  );
  const remove = useCallback(
    (key: string) => {
      const media = uploads.items.find((item) => item.key === key)?.media;
      if (!failures.has(key) || !media) {
        drop(key);
        discard(key);
        return;
      }
      // не прикрепилось: пока портфолио перечитывается, эффект не прикрепляет файл снова
      attaching.current.add(key);
      void queryClient
        .fetchQuery(getSpecialistsGetMyPortfolioQueryOptions())
        .then(
          (fresh) => fresh.items.some((work) => work.media?.id === media.id),
          () => false,
        )
        .then((attached) => {
          if (attached) forget(key);
          else discard(key);
          drop(key);
          attaching.current.delete(key);
        });
    },
    [discard, drop, failures, forget, queryClient, uploads.items],
  );

  return { items, add, retry, remove, previews };
}
