// Загрузки формы (аватар, портфолио, фото заявки): плитки с прогрессом, повтор, удаление
// (DEVELOPMENT_PLAN 2.1). Сама передача — MediaUpload, транспорт даёт платформа.
// - файлы идут по два разом: на слабой сети первые доходят раньше, а не все вместе в конце;
// - после complete — опрос GET /media/{id}: отклонённый при обработке файл (2.2) — ошибка
//   без повтора; обработка дольше таймаута — не ошибка, файл уже загружен;
// - «Убрать» останавливает передачу и удаляет запись на сервере; `reset` после отправки формы
//   забывает файлы, не удаляя их, `forget` — один загруженный (уже прикреплён: работа портфолио);
// - уход с экрана останавливает незаконченные загрузки: без формы они никому не нужны.
import type { MediaOut, MediaPurpose } from '@sosed/api-client';
import { ApiError, RestrictedError } from '@sosed/api-client';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import type { MediaApi, MediaTransport } from './upload.ts';
import {
  MediaRejectedError,
  MediaUpload,
  UploadCancelledError,
  mediaApi,
  waitForMedia,
} from './upload.ts';

/** Загрузок одновременно на одну форму. */
export const UPLOADS_AT_ONCE = 2;

export type UploadStatus = 'uploading' | 'uploaded' | 'failed';

export interface UploadItem {
  readonly key: string;
  readonly file: Blob & { readonly name?: string };
  readonly status: UploadStatus;
  /** Доля отправленного, 0…1. */
  readonly progress: number;
  /** Превью для плитки после загрузки; `null` — показать нечего (видео, HEIC). */
  readonly preview: Blob | null;
  /** Ответ сервера после complete и опроса; до загрузки — `null`. */
  readonly media: MediaOut | null;
  /** Почему `failed`. */
  readonly error: unknown;
  /** Поможет ли «Повторить»: нет — если файл отклонён (тип, размер, обработка). */
  readonly retryable: boolean;
}

export interface MediaUploadsOptions {
  purpose: MediaPurpose;
  transport: MediaTransport;
  /** Сколько файлов можно добавить всего. */
  max?: number;
  api?: MediaApi;
  sleep?: (ms: number) => Promise<void>;
  pollTimeoutMs?: number;
}

export interface MediaUploads {
  readonly items: readonly UploadItem[];
  /** Добавить файлы; вернёт, сколько не поместилось в `max`. */
  add(files: Iterable<Blob & { readonly name?: string }>): number;
  /** Догрузить упавший файл. */
  retry(key: string): void;
  /** Убрать файл: передача останавливается, запись на сервере удаляется. */
  remove(key: string): void;
  /** Забыть все файлы, не удаляя их: форма уже отправлена. */
  reset(): void;
  /** Забыть загруженный файл, не удаляя его: он уже прикреплён. Незагруженный — ничего. */
  forget(key: string): void;
  /** Id загруженных файлов в порядке добавления — для отправки формы. */
  readonly mediaIds: readonly string[];
  /** Идёт загрузка: отправку формы стоит подождать. */
  readonly uploading: boolean;
}

interface Task {
  upload: MediaUpload;
  /** complete прошёл: уход с экрана файл уже не удаляет. */
  done: boolean;
  poll: AbortController | null;
}

/** 4xx по файлу (тип, размер, расхождение с HEAD) и отказ обработки не лечатся повтором. */
export function isRetryable(error: unknown): boolean {
  if (error instanceof MediaRejectedError || error instanceof RestrictedError) return false;
  if (error instanceof ApiError) {
    return error.status >= 500 || [401, 408, 409, 429].includes(error.status);
  }
  return true;
}

function limiter(limit: number) {
  let active = 0;
  const waiting: (() => void)[] = [];
  return async <T>(task: () => Promise<T>): Promise<T> => {
    if (active >= limit) await new Promise<void>((resolve) => waiting.push(resolve));
    active += 1;
    try {
      return await task();
    } finally {
      active -= 1;
      waiting.shift()?.();
    }
  };
}

export function useMediaUploads(options: MediaUploadsOptions): MediaUploads {
  const { max = Number.POSITIVE_INFINITY } = options;
  // назначение, транспорт и API — на всю жизнь формы: берём из первого рендера
  const [config] = useState(() => ({
    purpose: options.purpose,
    transport: options.transport,
    api: options.api ?? mediaApi,
    sleep: options.sleep,
    pollTimeoutMs: options.pollTimeoutMs,
    limit: limiter(UPLOADS_AT_ONCE),
  }));
  const [items, setItems] = useState<readonly UploadItem[]>([]);
  const tasks = useRef(new Map<string, Task>());
  const counter = useRef(0);

  const update = useCallback((key: string, patch: Partial<UploadItem>) => {
    setItems((current) => current.map((item) => (item.key === key ? { ...item, ...patch } : item)));
  }, []);

  const start = useCallback(
    (key: string) => {
      const task = tasks.current.get(key);
      if (!task) return;
      update(key, { status: 'uploading', error: null, retryable: true });
      const finish = async (media: MediaOut) => {
        task.done = true;
        if (!tasks.current.has(key)) return;
        update(key, { status: 'uploaded', progress: 1, preview: task.upload.preview, media });
        const poll = new AbortController();
        task.poll = poll;
        try {
          const settled = await waitForMedia(media, {
            api: config.api,
            sleep: config.sleep,
            signal: poll.signal,
            timeoutMs: config.pollTimeoutMs,
          });
          update(key, { media: settled });
        } catch (error) {
          // сбой опроса — не сбой загрузки: файл уже на сервере
          if (error instanceof MediaRejectedError && tasks.current.has(key)) {
            update(key, { status: 'failed', media: error.media, error, retryable: false });
          }
        }
      };
      config
        .limit(() => task.upload.run())
        .then(finish, (error: unknown) => {
          if (error instanceof UploadCancelledError || !tasks.current.has(key)) return;
          update(key, { status: 'failed', error, retryable: isRetryable(error) });
        });
    },
    [config, update],
  );

  const add = useCallback(
    (files: Iterable<Blob & { readonly name?: string }>) => {
      const list = [...files];
      const room = Math.max(0, max - tasks.current.size);
      const accepted = list.slice(0, room);
      const added = accepted.map((file): UploadItem => {
        counter.current += 1;
        const key = `upload-${counter.current}`;
        let percent = 0;
        const upload = new MediaUpload(file, config.purpose, {
          api: config.api,
          transport: config.transport,
          sleep: config.sleep,
          // XHR шлёт прогресс десятки раз в секунду: перерисовка — только на новый процент
          onProgress: (progress) => {
            const next = Math.floor(progress * 100);
            if (next === percent) return;
            percent = next;
            update(key, { progress });
          },
        });
        tasks.current.set(key, { upload, done: false, poll: null });
        return {
          key,
          file,
          status: 'uploading',
          progress: 0,
          preview: null,
          media: null,
          error: null,
          retryable: true,
        };
      });
      if (added.length > 0) setItems((current) => [...current, ...added]);
      for (const item of added) start(item.key);
      return list.length - accepted.length;
    },
    [config, max, start, update],
  );

  const retry = useCallback(
    (key: string) => {
      const item = items.find((candidate) => candidate.key === key);
      if (item?.status === 'failed' && item.retryable) start(key);
    },
    [items, start],
  );

  const remove = useCallback((key: string) => {
    const task = tasks.current.get(key);
    tasks.current.delete(key);
    setItems((current) => current.filter((item) => item.key !== key));
    if (!task) return;
    task.poll?.abort(new UploadCancelledError());
    // не удалилось (сеть) — запись уберёт сервер: незавершённые — media.cleanup_orphans
    void task.upload.cancel().catch(() => undefined);
  }, []);

  const reset = useCallback(() => {
    for (const task of tasks.current.values()) task.poll?.abort(new UploadCancelledError());
    tasks.current.clear();
    setItems([]);
  }, []);

  const forget = useCallback((key: string) => {
    const task = tasks.current.get(key);
    // незагруженный файл без задачи никто бы не остановил и не удалил
    if (!task?.done) return;
    tasks.current.delete(key);
    task.poll?.abort(new UploadCancelledError());
    setItems((current) => current.filter((item) => item.key !== key));
  }, []);

  useEffect(() => {
    const current = tasks.current;
    return () => {
      for (const task of current.values()) {
        task.poll?.abort(new UploadCancelledError());
        if (!task.done) void task.upload.cancel().catch(() => undefined);
      }
    };
  }, []);

  const mediaIds = useMemo(
    () =>
      items.flatMap((item) => (item.status === 'uploaded' && item.media ? [item.media.id] : [])),
    [items],
  );
  const uploading = items.some((item) => item.status === 'uploading');

  return { items, add, retry, remove, reset, forget, mediaIds, uploading };
}
