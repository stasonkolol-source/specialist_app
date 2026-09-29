// Загрузка файла в хранилище по presigned-ссылкам (DEVELOPMENT_PLAN 2.1, ADR-0007, спайк 0.24).
//
// - POST /media/uploads: файл до 50 MB — одним PUT, видео больше — частями по 8 MiB.
//   Idempotency-Key один на загрузку: повтор старта после потерянного ответа вернёт ту же запись.
// - PUT идёт прямо в хранилище через транспорт платформы (в вебе — XHR ради прогресса).
//   Обрыв сети (status 0) и 5xx — повтор той же ссылки с паузой 1, 2, 4, 8 с; 400/403 — ссылка
//   истекла (Garage — 400, R2 — 403): новая ссылка через POST /media/uploads/{id}/parts.
// - Части — по 3 параллельно, ETag каждой — из ответа (CORS бакета: ExposeHeaders ETag). Первая
//   окончательно упавшая часть останавливает остальные; `run` ещё раз догружает недостающие.
// - POST …/complete: сервер сверяет файл HEAD-ом. 409 `media_upload_incomplete` — части
//   (`missing_parts`) или файл не дошли: они забываются, и «Повторить» догружает их.
//   Дальше обработка (2.2): `waitForMedia` опрашивает GET /media/{id}, пока файл не готов.
// Пакет headless: DOM (canvas, XHR) — в транспорте, который передаёт приложение.
import type { MediaOut, MediaPurpose, SignedPartOut, UploadOut } from '@sosed/api-client';
import {
  ApiError,
  mediaCompleteUpload,
  mediaDeleteMedia,
  mediaGetMedia,
  mediaSignUploadParts,
  mediaStartUpload,
} from '@sosed/api-client';

export interface PutResult {
  /** HTTP-статус; 0 — ответа нет (обрыв сети, CORS, зависшая передача). */
  status: number;
  etag: string | null;
}

export interface Prepared {
  /** Что уходит в хранилище: фото — уменьшенное до ≈2048 px, остальное — как есть. */
  body: Blob;
  /** Маленькая копия для плитки; `null` — показать нечего (видео, HEIC без декодера). */
  preview: Blob | null;
}

/** Передача файла, своя у каждой платформы (веб — packages/platform). */
export interface MediaTransport {
  /** PUT файла или части по presigned-ссылке; `onProgress` — сколько байт отправлено. */
  put(
    url: string,
    body: Blob,
    headers: Readonly<Record<string, string>>,
    onProgress: (loaded: number) => void,
    signal: AbortSignal,
  ): Promise<PutResult>;
  /** Подготовить файл к загрузке; не вышло — вернуть его как есть. Без реализации — как есть. */
  prepare?(file: Blob): Promise<Prepared>;
}

export interface MediaApi {
  start(
    body: { purpose: MediaPurpose; mime_type: string; size_bytes: number },
    key: string,
  ): Promise<UploadOut>;
  sign(mediaId: string, partNumbers: number[] | null): Promise<UploadOut>;
  complete(mediaId: string, parts: { part_number: number; etag: string }[]): Promise<MediaOut>;
  get(mediaId: string): Promise<MediaOut>;
  remove(mediaId: string): Promise<void>;
}

/** API через api-client: сессия, 401 → refresh, типизированные ошибки — как у всех запросов. */
export const mediaApi: MediaApi = {
  start: (body, key) => mediaStartUpload(body, { 'Idempotency-Key': key }),
  sign: (mediaId, partNumbers) => mediaSignUploadParts(mediaId, { part_numbers: partNumbers }),
  complete: (mediaId, parts) => mediaCompleteUpload(mediaId, { parts }),
  get: (mediaId) => mediaGetMedia(mediaId),
  remove: (mediaId) => mediaDeleteMedia(mediaId),
};

/** Части multipart, которые идут одновременно. */
export const PARALLEL = 3;
/** Попыток на часть: пауза между ними 1, 2, 4, 8 с. */
export const ATTEMPTS = 5;

const EXTENSIONS: Record<string, string> = {
  heic: 'image/heic',
  heif: 'image/heif',
  jpg: 'image/jpeg',
  jpeg: 'image/jpeg',
  png: 'image/png',
  webp: 'image/webp',
  mp4: 'video/mp4',
  mov: 'video/quicktime',
};

/**
 * Тип файла для POST /media/uploads. Android WebView отдаёт HEIC с пустым `type` — тогда тип по
 * расширению; незнакомое — `application/octet-stream`, и сервер ответит понятной ошибкой.
 */
export function contentTypeOf(file: { name?: string; type: string }): string {
  if (file.type) return file.type;
  const ext = file.name?.split('.').pop()?.toLowerCase() ?? '';
  return EXTENSIONS[ext] ?? 'application/octet-stream';
}

/** Хранилище не приняло часть после всех попыток или не отдало ETag. */
export class UploadFailedError extends Error {
  override name = 'UploadFailedError';
}

/** Загрузку отменили: запись на сервере удалена или будет удалена. */
export class UploadCancelledError extends Error {
  override name = 'UploadCancelledError';
}

/** Сервер не принял файл при обработке (2.2): не картинка, bomb, модерация. */
export class MediaRejectedError extends Error {
  override name = 'MediaRejectedError';
  readonly media: MediaOut;

  constructor(media: MediaOut) {
    super(`media ${media.id} is ${media.status}`);
    this.media = media;
  }
}

export interface MediaUploadOptions {
  api?: MediaApi;
  transport: MediaTransport;
  sleep?: (ms: number) => Promise<void>;
  /** Idempotency-Key старта (в тестах — предсказуемый). */
  newKey?: () => string;
  /** Доля отправленного, 0…1. */
  onProgress?: (fraction: number) => void;
}

type File_ = Blob & { readonly name?: string };

/**
 * Одна загрузка. Помнит план и готовые части: `run` после сбоя догружает только недостающее.
 * `cancel` окончательный: передача останавливается, запись на сервере удаляется.
 */
export class MediaUpload {
  readonly file: File_;
  readonly purpose: MediaPurpose;
  private plan: UploadOut | null = null;
  private body: Blob | null = null;
  private thumbnail: Blob | null = null;
  private running: Promise<MediaOut> | null = null;
  private controller: AbortController | null = null;
  private cancelled = false;
  private readonly etags = new Map<number, string>();
  private readonly loaded = new Map<number, number>();
  private readonly key: string;
  private readonly api: MediaApi;
  private readonly transport: MediaTransport;
  private readonly sleep: (ms: number) => Promise<void>;
  private readonly onProgress: (fraction: number) => void;

  constructor(file: File_, purpose: MediaPurpose, options: MediaUploadOptions) {
    this.file = file;
    this.purpose = purpose;
    this.api = options.api ?? mediaApi;
    this.transport = options.transport;
    this.sleep = options.sleep ?? wait;
    this.key = options.newKey?.() ?? crypto.randomUUID();
    this.onProgress = options.onProgress ?? (() => undefined);
  }

  get mediaId(): string | null {
    return this.plan?.media_id ?? null;
  }

  /** Превью для плитки (после подготовки файла); `null` — показать нечего. */
  get preview(): Blob | null {
    return this.thumbnail;
  }

  /** Загрузить (или догрузить после сбоя) и завершить. Повторный вызов во время работы — тот же промис. */
  run(): Promise<MediaOut> {
    this.running ??= this.execute().finally(() => {
      this.running = null;
    });
    return this.running;
  }

  /** Отменить: остановить передачу и удалить запись на сервере (multipart отменит сервер). */
  async cancel(): Promise<void> {
    if (this.cancelled) return;
    this.cancelled = true;
    this.controller?.abort(new UploadCancelledError());
    const plan = this.plan;
    this.plan = null;
    if (plan) await this.api.remove(plan.media_id);
  }

  private async execute(): Promise<MediaOut> {
    this.ensureActive();
    const controller = new AbortController();
    this.controller = controller;
    const body = await this.prepare();
    this.ensureActive();
    const plan = await this.started(body);
    const pending = plan.parts.filter((part) => !this.etags.has(part.part_number ?? 1));
    await runLimited(pending, PARALLEL, controller, (part) =>
      this.uploadPart(plan, body, part, controller.signal),
    );
    this.ensureActive();
    const parts = plan.multipart
      ? [...this.etags].map(([part_number, etag]) => ({ part_number, etag }))
      : [];
    try {
      return await this.api.complete(plan.media_id, parts);
    } catch (error) {
      if (error instanceof ApiError && error.code === 'media_upload_incomplete') {
        this.forget(plan, error.problem['missing_parts']);
      }
      throw error;
    }
  }

  /** Сервер не нашёл части (или файл): следующий `run` загрузит их заново. */
  private forget(plan: UploadOut, missing: unknown) {
    const numbers = Array.isArray(missing) ? missing.filter((n) => typeof n === 'number') : null;
    for (const number of numbers ?? [...this.etags.keys()]) {
      this.etags.delete(number);
      this.progress(plan, number, 0);
    }
  }

  private ensureActive() {
    if (this.cancelled) throw new UploadCancelledError();
  }

  private async started(body: Blob): Promise<UploadOut> {
    if (this.plan) return this.plan;
    const plan = await this.api.start(
      { purpose: this.purpose, mime_type: body.type, size_bytes: body.size },
      this.key,
    );
    if (this.cancelled) {
      // отменили, пока ждали ответа: запись уже есть — убрать её
      await this.api.remove(plan.media_id).catch(() => undefined);
      throw new UploadCancelledError();
    }
    this.plan = plan;
    return plan;
  }

  /** Файл с типом (HEIC без `type` — по расширению), подготовленный платформой. */
  private async prepare(): Promise<Blob> {
    if (this.body) return this.body;
    const type = contentTypeOf({ name: this.file.name, type: this.file.type });
    const typed = this.file.type === type ? this.file : this.file.slice(0, this.file.size, type);
    const prepared = this.transport.prepare
      ? await this.transport.prepare(typed)
      : { body: typed, preview: null };
    this.body = prepared.body;
    this.thumbnail = prepared.preview;
    return prepared.body;
  }

  private async uploadPart(
    plan: UploadOut,
    file: Blob,
    signed: SignedPartOut,
    signal: AbortSignal,
  ): Promise<void> {
    const number = signed.part_number ?? 1;
    const partSize = plan.part_size ?? file.size;
    const start = (number - 1) * partSize;
    const body = plan.multipart ? file.slice(start, Math.min(start + partSize, file.size)) : file;
    let link = signed;
    for (let attempt = 1; ; attempt += 1) {
      signal.throwIfAborted();
      const result = await this.transport.put(
        link.url,
        body,
        link.headers,
        (loaded) => this.progress(plan, number, loaded),
        signal,
      );
      signal.throwIfAborted();
      if (result.status >= 200 && result.status < 300) {
        if (plan.multipart && !result.etag) {
          throw new UploadFailedError('нет ETag в ответе: CORS бакета не отдаёт ETag');
        }
        this.etags.set(number, result.etag ?? '');
        this.progress(plan, number, body.size);
        return;
      }
      this.progress(plan, number, 0);
      if (attempt >= ATTEMPTS) throw new UploadFailedError(`часть ${number}: ${result.status}`);
      if (result.status === 400 || result.status === 403) {
        const fresh = await this.api.sign(plan.media_id, plan.multipart ? [number] : null);
        link = fresh.parts[0] ?? link;
      } else {
        await abortable(this.sleep(1000 * 2 ** (attempt - 1)), signal);
      }
    }
  }

  private progress(plan: UploadOut, number: number, loaded: number) {
    if (this.plan !== plan) return; // отменили: старый план больше не показываем
    this.loaded.set(number, loaded);
    const total = this.body?.size ?? this.file.size;
    let sum = 0;
    for (const value of this.loaded.values()) sum += value;
    this.onProgress(total > 0 ? Math.min(1, sum / total) : 0);
  }
}

/** Статусы, после которых опрос не нужен. */
const SETTLED = new Set<MediaOut['status']>(['ready', 'failed', 'rejected', 'deleted']);
/** Паузы опроса; дальше — последняя. */
export const POLL_DELAYS = [1000, 2000, 3000, 5000];

export interface WaitOptions {
  api?: MediaApi;
  signal?: AbortSignal;
  sleep?: (ms: number) => Promise<void>;
  /** Сколько опрашивать; потом — последний ответ (обработка идёт, файл уже загружен). */
  timeoutMs?: number;
}

/**
 * Опрос GET /media/{id} после complete, пока обработка (2.2) не закончится или не выйдет время.
 * Отклонённый файл — MediaRejectedError. До 2.2 файл так и остаётся `uploaded`: это не ошибка.
 */
export async function waitForMedia(media: MediaOut, options: WaitOptions = {}): Promise<MediaOut> {
  const api = options.api ?? mediaApi;
  const sleep = options.sleep ?? wait;
  const timeout = options.timeoutMs ?? 30_000;
  let current = media;
  let waited = 0;
  for (let i = 0; !SETTLED.has(current.status) && waited < timeout; i += 1) {
    const delay = POLL_DELAYS[Math.min(i, POLL_DELAYS.length - 1)] ?? 5000;
    await (options.signal ? abortable(sleep(delay), options.signal) : sleep(delay));
    waited += delay;
    current = await api.get(current.id);
  }
  if (current.status === 'failed' || current.status === 'rejected') {
    throw new MediaRejectedError(current);
  }
  return current;
}

/**
 * Не больше `limit` задач разом. Первая ошибка останавливает остальные через `stop`; промис
 * завершается, когда закончились все начатые задачи.
 */
async function runLimited<T>(
  items: readonly T[],
  limit: number,
  stop: AbortController,
  run: (item: T) => Promise<void>,
): Promise<void> {
  const queue = [...items];
  let failure: { error: unknown } | null = null;
  const worker = async () => {
    for (let item = queue.shift(); item !== undefined && !failure; item = queue.shift()) {
      try {
        await run(item);
      } catch (error) {
        if (!failure) {
          failure = { error };
          stop.abort(error);
        }
      }
    }
  };
  await Promise.all(Array.from({ length: Math.min(limit, queue.length) }, worker));
  if (failure) throw (failure as { error: unknown }).error;
}

/** Пауза, которую прерывает отмена: иначе остановка ждала бы конца бэкоффа. */
function abortable(promise: Promise<void>, signal: AbortSignal): Promise<void> {
  if (signal.aborted) return Promise.reject(signal.reason as Error);
  return new Promise((resolve, reject) => {
    const onAbort = () => reject(signal.reason as Error);
    signal.addEventListener('abort', onAbort, { once: true });
    promise.then(resolve, reject).finally(() => signal.removeEventListener('abort', onAbort));
  });
}

const wait = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));
