import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { MAX_SIDE, PREVIEW_SIDE, STALL_MS, prepareImage, xhrPut } from './media.ts';

type Listener = () => void;

class FakeXhr {
  static last: FakeXhr;
  method = '';
  url = '';
  headers: Record<string, string> = {};
  body: unknown = null;
  status = 0;
  etag: string | null = null;
  private readonly listeners = new Map<string, Listener[]>();
  private readonly uploadListeners: ((event: { loaded: number }) => void)[] = [];
  readonly upload = {
    addEventListener: (_type: string, listener: (event: { loaded: number }) => void) => {
      this.uploadListeners.push(listener);
    },
  };

  constructor() {
    FakeXhr.last = this;
  }

  open(method: string, url: string) {
    this.method = method;
    this.url = url;
  }

  setRequestHeader(name: string, value: string) {
    this.headers[name] = value;
  }

  addEventListener(type: string, listener: Listener) {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
  }

  getResponseHeader(name: string) {
    return name === 'ETag' ? this.etag : null;
  }

  send(body: unknown) {
    this.body = body;
  }

  abort() {
    this.emit('abort');
  }

  emit(type: string) {
    for (const listener of this.listeners.get(type) ?? []) listener();
  }

  progress(loaded: number) {
    for (const listener of this.uploadListeners) listener({ loaded });
  }

  respond(status: number, etag: string | null = null) {
    this.status = status;
    this.etag = etag;
    this.emit('load');
  }
}

describe('PUT по presigned-ссылке', () => {
  beforeEach(() => vi.stubGlobal('XMLHttpRequest', FakeXhr));
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it('шлёт подписанные заголовки, сообщает прогресс и отдаёт ETag', async () => {
    const body = new Blob(['abc']);
    const progress = vi.fn();

    const put = xhrPut(
      'https://s3.test/one',
      body,
      { 'Content-Type': 'image/jpeg' },
      progress,
      new AbortController().signal,
    );
    FakeXhr.last.progress(2);
    FakeXhr.last.respond(200, '"e1"');

    await expect(put).resolves.toEqual({ status: 200, etag: '"e1"' });
    expect(FakeXhr.last).toMatchObject({
      method: 'PUT',
      url: 'https://s3.test/one',
      headers: { 'Content-Type': 'image/jpeg' },
      body,
    });
    expect(progress).toHaveBeenCalledWith(2);
  });

  it('обрыв сети — статус 0: загрузчик повторит', async () => {
    const put = xhrPut(
      'https://s3.test/one',
      new Blob(['a']),
      {},
      () => undefined,
      new AbortController().signal,
    );
    FakeXhr.last.emit('error');

    await expect(put).resolves.toEqual({ status: 0, etag: null });
  });

  it('отмена обрывает передачу и отклоняет промис', async () => {
    const controller = new AbortController();
    const put = xhrPut(
      'https://s3.test/one',
      new Blob(['a']),
      {},
      () => undefined,
      controller.signal,
    );
    controller.abort(new Error('отменили'));

    await expect(put).rejects.toThrow('отменили');
  });

  it('зависшая передача без прогресса считается обрывом сети', async () => {
    vi.useFakeTimers();
    const put = xhrPut(
      'https://s3.test/one',
      new Blob(['a']),
      {},
      () => undefined,
      new AbortController().signal,
    );
    vi.advanceTimersByTime(STALL_MS - 1000);
    FakeXhr.last.progress(1); // прогресс продлевает ожидание
    vi.advanceTimersByTime(STALL_MS - 1000);
    let settled = false;
    void put.then(() => (settled = true));
    await Promise.resolve();
    expect(settled).toBe(false);

    vi.advanceTimersByTime(1000);

    await expect(put).resolves.toEqual({ status: 0, etag: null });
  });
});

describe('подготовка фото', () => {
  const canvases: { width: number; height: number }[] = [];
  const context = {
    fillStyle: '',
    imageSmoothingQuality: 'low',
    fillRect: vi.fn(),
    drawImage: vi.fn(),
  };

  class FakeOffscreenCanvas {
    constructor(width: number, height: number) {
      canvases.push({ width, height });
    }

    getContext() {
      return context;
    }

    async convertToBlob(options: { type: string }) {
      return new Blob(['x'.repeat(10)], { type: options.type });
    }
  }

  const bitmap = (width: number, height: number) => {
    const close = vi.fn();
    vi.stubGlobal(
      'createImageBitmap',
      vi.fn(async () => ({ width, height, close })),
    );
    return close;
  };

  beforeEach(() => {
    canvases.length = 0;
    vi.stubGlobal('OffscreenCanvas', FakeOffscreenCanvas);
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    Reflect.deleteProperty(HTMLImageElement.prototype, 'decode');
  });

  // в jsdom нет HTMLImageElement.decode
  const stubDecode = (decode: () => Promise<void>) =>
    Object.defineProperty(HTMLImageElement.prototype, 'decode', {
      configurable: true,
      value: decode,
    });

  it('уменьшает большое фото до 2048 px и делает превью', async () => {
    const close = bitmap(4000, 3000);
    const photo = new Blob(['p'.repeat(4096)], { type: 'image/heic' });

    const { body, preview } = await prepareImage(photo);

    expect(canvases).toEqual([
      { width: MAX_SIDE, height: 1536 },
      { width: PREVIEW_SIDE, height: 240 },
    ]);
    expect(body.type).toBe('image/jpeg');
    expect(preview?.type).toBe('image/jpeg');
    expect(close).toHaveBeenCalled();
    // поворот по EXIF делает декодер
    expect(createImageBitmap).toHaveBeenCalledWith(photo, { imageOrientation: 'from-image' });
  });

  it('маленькое фото уходит как есть, превью — всё равно', async () => {
    bitmap(1200, 900);
    const photo = new Blob(['p'.repeat(100)], { type: 'image/jpeg' });

    const { body, preview } = await prepareImage(photo);

    expect(body).toBe(photo);
    expect(preview).not.toBeNull();
    expect(canvases).toEqual([{ width: PREVIEW_SIDE, height: 240 }]);
  });

  it('видео не трогает', async () => {
    const video = new Blob(['v'], { type: 'video/mp4' });

    await expect(prepareImage(video)).resolves.toEqual({ body: video, preview: null });
  });

  it('HEIC, который браузер не декодирует, уходит как есть: сервер конвертирует сам', async () => {
    vi.stubGlobal(
      'createImageBitmap',
      vi.fn(async () => {
        throw new DOMException('The source image could not be decoded', 'InvalidStateError');
      }),
    );
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: () => 'blob:1' });
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() });
    stubDecode(vi.fn().mockRejectedValue(new Error('EncodingError')));
    const heic = new Blob(['h'], { type: 'image/heic' });

    await expect(prepareImage(heic)).resolves.toEqual({ body: heic, preview: null });
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:1');
  });

  it('без createImageBitmap и OffscreenCanvas — <img> и <canvas>', async () => {
    vi.stubGlobal('createImageBitmap', undefined);
    vi.stubGlobal('OffscreenCanvas', undefined);
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: () => 'blob:2' });
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() });
    stubDecode(vi.fn().mockResolvedValue(undefined));
    vi.spyOn(HTMLImageElement.prototype, 'naturalWidth', 'get').mockReturnValue(3000);
    vi.spyOn(HTMLImageElement.prototype, 'naturalHeight', 'get').mockReturnValue(4000);
    const sizes: [number, number][] = [];
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(
      context as unknown as CanvasRenderingContext2D,
    );
    vi.spyOn(HTMLCanvasElement.prototype, 'toBlob').mockImplementation(function (
      this: HTMLCanvasElement,
      callback: BlobCallback,
      type?: string,
    ) {
      sizes.push([this.width, this.height]);
      callback(new Blob(['c'], { type }));
    });
    const photo = new Blob(['p'.repeat(4096)], { type: 'image/png' });

    const { body } = await prepareImage(photo);

    expect(body.type).toBe('image/jpeg');
    expect(sizes).toEqual([
      [1536, MAX_SIDE],
      [240, PREVIEW_SIDE],
    ]);
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:2');
  });
});
