// Загрузчик спайка 0.24: файл идёт с телефона прямо в S3 по presigned-ссылкам backend.
//
// - До part_size — один PUT, больше — multipart: части параллельно по PARALLEL штук, ETag
//   каждой части читается из ответа (CORS бакета: ExposeHeaders ETag).
// - Обрыв сети (status 0) и 5xx — повтор той же ссылки с паузой; 400/403 — ссылка истекла
//   (Garage — 400, R2 — 403): просим у backend новую и повторяем.
// - Задача помнит план и готовые части: «Повторить» после обрыва догружает только недостающее.
// Шаг 2.1 переносит это в модуль медиа (или заменяет на Uppy @uppy/aws-s3 — см. записку спайка).

export interface SignedUrl {
  part_number: number | null;
  url: string;
  headers: Record<string, string>;
  expires_at: string;
}

export interface UploadPlan {
  key: string;
  upload_id: string | null;
  part_size: number;
  parts: SignedUrl[];
}

export interface StoredObject {
  key: string;
  size: number;
  content_type: string | null;
  etag: string;
  url: string;
}

export interface SpikeApi {
  start(body: { filename: string; content_type: string; size: number }): Promise<UploadPlan>;
  sign(body: {
    key: string;
    content_type: string;
    size: number;
    upload_id: string | null;
    part_number: number | null;
  }): Promise<SignedUrl>;
  complete(body: {
    key: string;
    upload_id: string;
    parts: { part_number: number; etag: string }[];
  }): Promise<void>;
  abort(body: { key: string; upload_id: string }): Promise<void>;
  head(key: string): Promise<StoredObject>;
}

export interface PutResult {
  /** 0 — сеть оборвалась, ответа нет. */
  status: number;
  etag: string | null;
}

export type Put = (
  url: string,
  body: Blob,
  headers: Record<string, string>,
  onProgress: (loaded: number) => void,
  signal: AbortSignal,
) => Promise<PutResult>;

export interface UploadDeps {
  api: SpikeApi;
  put: Put;
  log: (message: string) => void;
  sleep?: (ms: number) => Promise<void>;
  now?: () => number;
  /** Попыток на часть, включая первую. */
  attempts?: number;
}

export const PARALLEL = 3;
const EXTENSIONS: Record<string, string> = {
  heic: 'image/heic',
  heif: 'image/heif',
  jpg: 'image/jpeg',
  jpeg: 'image/jpeg',
  png: 'image/png',
  webp: 'image/webp',
  mp4: 'video/mp4',
  mov: 'video/quicktime',
  webm: 'video/webm',
};

/** Android WebView отдаёт HEIC с пустым type: тогда тип по расширению. */
export function contentTypeOf(file: { name: string; type: string }): string {
  if (file.type) return file.type;
  const ext = file.name.split('.').pop()?.toLowerCase() ?? '';
  return EXTENSIONS[ext] ?? '';
}

export class UploadFailedError extends Error {}

export interface UploadResult {
  stored: StoredObject;
  /** Длительность этого запуска `run`, мс. */
  ms: number;
}

export class UploadTask {
  readonly file: File;
  readonly contentType: string;
  plan: UploadPlan | null = null;
  readonly etags = new Map<number, string>();
  private readonly loaded = new Map<number, number>();
  private readonly deps: UploadDeps;
  private readonly onProgress: (loaded: number, total: number) => void;

  constructor(
    file: File,
    deps: UploadDeps,
    onProgress: (loaded: number, total: number) => void = () => undefined,
  ) {
    this.file = file;
    this.deps = deps;
    this.onProgress = onProgress;
    this.contentType = contentTypeOf(file);
  }

  /** Загрузить (или догрузить после обрыва) и проверить HEAD: размер совпадает с файлом. */
  async run(signal: AbortSignal): Promise<UploadResult> {
    const { api, log, now = () => performance.now() } = this.deps;
    const startedAt = now();
    this.plan ??= await api.start({
      filename: this.file.name,
      content_type: this.contentType,
      size: this.file.size,
    });
    const plan = this.plan;
    const pending = plan.parts.filter((part) => !this.etags.has(part.part_number ?? 1));
    log(`${this.file.name}: ${plan.upload_id ? 'multipart' : 'PUT'}, частей ${pending.length}`);
    // свой контроллер на запуск: первая упавшая часть останавливает остальные
    const stop = new AbortController();
    const forward = () => stop.abort(signal.reason);
    signal.addEventListener('abort', forward, { once: true });
    try {
      await runLimited(pending, PARALLEL, stop, (part) => this.uploadPart(plan, part, stop.signal));
    } finally {
      signal.removeEventListener('abort', forward);
    }
    if (plan.upload_id) {
      const parts = [...this.etags].map(([part_number, etag]) => ({ part_number, etag }));
      await api.complete({ key: plan.key, upload_id: plan.upload_id, parts });
    }
    const stored = await api.head(plan.key);
    if (stored.size !== this.file.size) {
      throw new UploadFailedError(`HEAD: ${stored.size} байт вместо ${this.file.size}`);
    }
    return { stored, ms: now() - startedAt };
  }

  /** Отменить multipart на сервере (незавершённые части иначе ждут lifecycle) и забыть план:
   *  «Повторить» после отмены начинает загрузку заново. */
  async abort(): Promise<void> {
    const plan = this.plan;
    this.plan = null;
    this.etags.clear();
    this.loaded.clear();
    this.report();
    if (plan?.upload_id) {
      await this.deps.api.abort({ key: plan.key, upload_id: plan.upload_id });
    }
  }

  private async uploadPart(plan: UploadPlan, signed: SignedUrl, signal: AbortSignal) {
    const { api, put, log, sleep = wait, attempts = 5 } = this.deps;
    const number = signed.part_number ?? 1;
    const start = (number - 1) * plan.part_size;
    const body = plan.upload_id
      ? this.file.slice(start, Math.min(start + plan.part_size, this.file.size))
      : this.file;
    let link = signed;
    for (let attempt = 1; attempt <= attempts; attempt += 1) {
      signal.throwIfAborted();
      const result = await put(
        link.url,
        body,
        link.headers,
        (loaded) => {
          if (this.plan !== plan) return; // план сброшен отменой
          this.loaded.set(number, loaded);
          this.report();
        },
        signal,
      );
      signal.throwIfAborted();
      if (result.status >= 200 && result.status < 300) {
        if (plan.upload_id && !result.etag) {
          throw new UploadFailedError('нет ETag в ответе: CORS бакета не отдаёт ETag');
        }
        this.etags.set(number, result.etag ?? '');
        this.loaded.set(number, body.size);
        this.report();
        return;
      }
      this.loaded.set(number, 0);
      this.report();
      log(`${this.file.name} #${number}: попытка ${attempt} — ${result.status || 'обрыв сети'}`);
      if (attempt === attempts) break;
      if (result.status === 400 || result.status === 403) {
        link = await api.sign({
          key: plan.key,
          content_type: this.contentType,
          size: body.size,
          upload_id: plan.upload_id,
          part_number: signed.part_number,
        });
      } else {
        await abortable(sleep(Math.min(1000 * 2 ** (attempt - 1), 15_000)), signal);
      }
    }
    throw new UploadFailedError(`часть ${number} не загрузилась`);
  }

  private report() {
    let sum = 0;
    for (const value of this.loaded.values()) sum += value;
    this.onProgress(sum, this.file.size);
  }
}

/** Не больше `limit` задач разом. Первая ошибка останавливает остальные через `stop`, а
 *  промис завершается, только когда все начатые задачи закончились: после отказа ни одна
 *  часть не продолжает грузиться параллельно с «Повторить». */
async function runLimited<T>(
  items: T[],
  limit: number,
  stop: AbortController,
  run: (item: T) => Promise<void>,
) {
  const queue = [...items];
  let failed = false;
  let failure: unknown;
  const worker = async () => {
    while (!failed && queue.length > 0) {
      const item = queue.shift() as T;
      try {
        await run(item);
      } catch (error) {
        if (!failed) {
          failed = true;
          failure = error;
          stop.abort(error);
        }
      }
    }
  };
  await Promise.all(Array.from({ length: Math.min(limit, queue.length) }, worker));
  if (failed) throw failure;
}

/** Пауза, которую прерывает отмена: иначе остановка ждёт окончания бэкоффа (до 15 с). */
function abortable(promise: Promise<void>, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const onAbort = () => reject(signal.reason);
    if (signal.aborted) {
      onAbort();
      return;
    }
    signal.addEventListener('abort', onAbort, { once: true });
    promise.then(resolve, reject).finally(() => signal.removeEventListener('abort', onAbort));
  });
}

const wait = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

/** PUT через XMLHttpRequest: у fetch нет прогресса отправки. */
export const xhrPut: Put = (url, body, headers, onProgress, signal) =>
  new Promise((resolve, reject) => {
    if (signal.aborted) {
      reject(signal.reason);
      return;
    }
    const xhr = new XMLHttpRequest();
    xhr.open('PUT', url);
    for (const [name, value] of Object.entries(headers)) xhr.setRequestHeader(name, value);
    xhr.upload.onprogress = (event) => onProgress(event.loaded);
    xhr.onload = () => resolve({ status: xhr.status, etag: xhr.getResponseHeader('ETag') });
    xhr.onerror = () => resolve({ status: 0, etag: null });
    xhr.ontimeout = () => resolve({ status: 0, etag: null });
    xhr.onabort = () => reject(new DOMException('aborted', 'AbortError'));
    signal.addEventListener('abort', () => xhr.abort(), { once: true });
    xhr.send(body);
  });
