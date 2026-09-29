// Веб-транспорт загрузки медиа для Telegram WebView и браузера (DEVELOPMENT_PLAN 2.1, спайк 0.24).
// Загрузчик — packages/hooks (MediaTransport): здесь только то, что требует DOM.
// - PUT — XMLHttpRequest: fetch не сообщает, сколько отправлено. Передача без прогресса дольше
//   STALL_MS обрывается и считается обрывом сети — загрузчик повторит её.
// - Фото уменьшается до ≈2048 px по длинной стороне (JPEG 0.85, без EXIF — холст его не
//   переносит) и получает превью 320 px для плитки. Декодер — createImageBitmap с поворотом по EXIF,
//   где его нет — <img>; холст — OffscreenCanvas, где его нет — <canvas>. Не декодируется
//   (HEIC в Chrome и Android) — файл уходит как есть: сервер конвертирует его сам (2.2).

export interface PutResult {
  /** HTTP-статус; 0 — ответа нет (обрыв сети, CORS, зависшая передача). */
  status: number;
  etag: string | null;
}

export interface PreparedMedia {
  body: Blob;
  preview: Blob | null;
}

/** Нет прогресса дольше — передача зависла (мобильная сеть «молчит», а не рвётся). */
export const STALL_MS = 45_000;
export const MAX_SIDE = 2048;
export const PREVIEW_SIDE = 320;
const QUALITY = 0.85;
/** Маленькое фото подходящего типа не пережимаем: качество не теряется, EXIF снимет сервер. */
const KEEP_BYTES = 1024 * 1024;
const KEEP_TYPES = new Set(['image/jpeg', 'image/png', 'image/webp']);

export function xhrPut(
  url: string,
  body: Blob,
  headers: Readonly<Record<string, string>>,
  onProgress: (loaded: number) => void,
  signal: AbortSignal,
): Promise<PutResult> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) {
      reject(signal.reason as Error);
      return;
    }
    const xhr = new XMLHttpRequest();
    let stalled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const watch = () => {
      clearTimeout(timer);
      timer = setTimeout(() => {
        stalled = true;
        xhr.abort();
      }, STALL_MS);
    };
    const onAbort = () => xhr.abort();
    const settle = () => {
      clearTimeout(timer);
      signal.removeEventListener('abort', onAbort);
    };
    xhr.open('PUT', url);
    for (const [name, value] of Object.entries(headers)) xhr.setRequestHeader(name, value);
    xhr.upload.addEventListener('progress', (event) => {
      watch();
      onProgress(event.loaded);
    });
    xhr.addEventListener('load', () => {
      settle();
      resolve({ status: xhr.status, etag: xhr.getResponseHeader('ETag') });
    });
    xhr.addEventListener('error', () => {
      settle();
      resolve({ status: 0, etag: null });
    });
    xhr.addEventListener('abort', () => {
      settle();
      if (stalled) resolve({ status: 0, etag: null });
      else reject(signal.reason as Error);
    });
    signal.addEventListener('abort', onAbort, { once: true });
    watch();
    xhr.send(body);
  });
}

interface Decoded {
  image: CanvasImageSource;
  width: number;
  height: number;
  release(): void;
}

async function decode(file: Blob): Promise<Decoded | null> {
  if (typeof createImageBitmap === 'function') {
    try {
      const bitmap = await createImageBitmap(file, { imageOrientation: 'from-image' });
      return {
        image: bitmap,
        width: bitmap.width,
        height: bitmap.height,
        release: () => bitmap.close(),
      };
    } catch {
      // старый WebView или формат, который createImageBitmap не берёт: пробуем <img>
    }
  }
  const url = URL.createObjectURL(file);
  try {
    const image = new Image();
    image.src = url;
    await image.decode();
    return {
      image,
      width: image.naturalWidth,
      height: image.naturalHeight,
      release: () => URL.revokeObjectURL(url),
    };
  } catch {
    URL.revokeObjectURL(url);
    return null;
  }
}

type Context2D = CanvasRenderingContext2D | OffscreenCanvasRenderingContext2D;

function paint(context: Context2D, source: Decoded, width: number, height: number) {
  // JPEG без прозрачности: прозрачный PNG иначе стал бы чёрным
  context.fillStyle = '#fff';
  context.fillRect(0, 0, width, height);
  context.imageSmoothingQuality = 'high';
  context.drawImage(source.image, 0, 0, width, height);
}

/** JPEG не больше `side` по длинной стороне; холст недоступен — `null`. */
async function encode(source: Decoded, side: number): Promise<Blob | null> {
  const scale = Math.min(1, side / Math.max(source.width, source.height));
  const width = Math.max(1, Math.round(source.width * scale));
  const height = Math.max(1, Math.round(source.height * scale));
  if (typeof OffscreenCanvas === 'function') {
    const canvas = new OffscreenCanvas(width, height);
    const context = canvas.getContext('2d');
    if (!context) return null;
    paint(context, source, width, height);
    return canvas.convertToBlob({ type: 'image/jpeg', quality: QUALITY });
  }
  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext('2d');
  if (!context) return null;
  paint(context, source, width, height);
  return new Promise((resolve) => canvas.toBlob(resolve, 'image/jpeg', QUALITY));
}

/** Фото — уменьшенное и с превью; всё остальное и то, что не декодируется, — как есть. */
export async function prepareImage(file: Blob): Promise<PreparedMedia> {
  if (!file.type.startsWith('image/')) return { body: file, preview: null };
  const source = await decode(file);
  if (!source) return { body: file, preview: null };
  try {
    const fits = Math.max(source.width, source.height) <= MAX_SIDE;
    let body = file;
    if (!(fits && file.size <= KEEP_BYTES && KEEP_TYPES.has(file.type))) {
      const encoded = await encode(source, MAX_SIDE).catch(() => null);
      // пережатое без уменьшения вышло больше исходного — исходный лучше
      if (encoded && !(fits && encoded.size >= file.size && KEEP_TYPES.has(file.type))) {
        body = encoded;
      }
    }
    const preview = await encode(source, PREVIEW_SIDE).catch(() => null);
    return { body, preview };
  } finally {
    source.release();
  }
}

/** Транспорт для useMediaUploads (packages/hooks) в Telegram WebView и браузере. */
export const webMediaTransport = {
  put: xhrPut,
  prepare: prepareImage,
};
