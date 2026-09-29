import type { UploadOut } from '@sosed/api-client';
import { ApiError } from '@sosed/api-client';
import { describe, expect, it, vi } from 'vitest';

import { fakeApi, media, planOf } from './testing.ts';
import type { MediaApi, MediaTransport, PutResult } from './upload.ts';
import {
  ATTEMPTS,
  MediaRejectedError,
  MediaUpload,
  UploadCancelledError,
  UploadFailedError,
  contentTypeOf,
  waitForMedia,
} from './upload.ts';

type Put = MediaTransport['put'];

const ok = (etag: string): PutResult => ({ status: 200, etag });
const noSleep = async () => {};

function uploadOf(file: Blob, api: MediaApi, put: Put, extra: Partial<MediaTransport> = {}) {
  const onProgress = vi.fn();
  const upload = new MediaUpload(file, 'portfolio', {
    api,
    transport: { put, ...extra },
    sleep: noSleep,
    newKey: () => 'key-1',
    onProgress,
  });
  return { upload, onProgress };
}

describe('contentTypeOf', () => {
  it('guesses HEIC by extension when WebView gives no type', () => {
    expect(contentTypeOf({ name: 'IMG_1.HEIC', type: '' })).toBe('image/heic');
    expect(contentTypeOf({ name: 'clip.MOV', type: '' })).toBe('video/quicktime');
  });

  it('keeps the type the browser knows and lets the server refuse the unknown', () => {
    expect(contentTypeOf({ name: 'a.jpg', type: 'image/png' })).toBe('image/png');
    expect(contentTypeOf({ name: 'notes.txt', type: '' })).toBe('application/octet-stream');
  });
});

describe('MediaUpload', () => {
  it('puts a photo once with the signed headers and completes without parts', async () => {
    const api = fakeApi(planOf([null]));
    const put = vi.fn<Put>(async () => ok('"e1"'));
    const { upload, onProgress } = uploadOf(
      new File(['abc'], 'a.jpg', { type: 'image/jpeg' }),
      api,
      put,
    );

    const result = await upload.run();

    expect(result.status).toBe('uploaded');
    expect(api.start).toHaveBeenCalledWith(
      { purpose: 'portfolio', mime_type: 'image/jpeg', size_bytes: 3 },
      'key-1',
    );
    expect(put).toHaveBeenCalledOnce();
    expect(put.mock.calls[0]?.[2]).toEqual({ 'Content-Type': 'image/jpeg' });
    expect(api.complete).toHaveBeenCalledWith('m1', []);
    expect(onProgress).toHaveBeenLastCalledWith(1);
    expect(upload.mediaId).toBe('m1');
  });

  it('uploads what the platform prepared and keeps its preview', async () => {
    const api = fakeApi(planOf([null]));
    const put = vi.fn<Put>(async () => ok('"e1"'));
    const small = new Blob(['xy'], { type: 'image/jpeg' });
    const thumb = new Blob(['t'], { type: 'image/jpeg' });
    const prepare = vi.fn(async (_file: Blob) => ({ body: small, preview: thumb }));
    const photo = new File(['a'.repeat(100)], 'IMG_2.HEIC', { type: '' });
    const { upload } = uploadOf(photo, api, put, { prepare });

    await upload.run();

    // HEIC без type получил тип по расширению ещё до платформы
    expect(prepare.mock.calls[0]?.[0].type).toBe('image/heic');
    expect(api.start).toHaveBeenCalledWith(
      { purpose: 'portfolio', mime_type: 'image/jpeg', size_bytes: 2 },
      'key-1',
    );
    expect(put.mock.calls[0]?.[1]).toBe(small);
    expect(upload.preview).toBe(thumb);
  });

  it('slices multipart, re-signs an expired part and completes with ETags', async () => {
    const api = fakeApi(planOf([1, 2, 3], 4));
    const sizes: number[] = [];
    const put = vi.fn<Put>(async (url, body) => {
      sizes.push(body.size);
      return url === 'https://s3.test/2' ? { status: 400, etag: null } : ok(`"${url}"`);
    });
    const { upload } = uploadOf(new File(['aaaabbbbcc'], 'v.mp4', { type: 'video/mp4' }), api, put);

    await upload.run();

    expect(sizes.sort()).toEqual([2, 4, 4, 4]);
    expect(api.sign).toHaveBeenCalledWith('m1', [2]);
    const parts = api.complete.mock.calls[0]?.[1] ?? [];
    expect(parts.map((p) => p.part_number).sort()).toEqual([1, 2, 3]);
    expect(parts.find((p) => p.part_number === 2)?.etag).toBe('"https://s3.test/fresh-2"');
  });

  it('asks for a new single link when R2 answers 403 to an expired one', async () => {
    const api = fakeApi(planOf([null]));
    const put = vi.fn<Put>(async (url) =>
      url.includes('fresh') ? ok('"e"') : { status: 403, etag: null },
    );
    const { upload } = uploadOf(new File(['abc'], 'a.jpg', { type: 'image/jpeg' }), api, put);

    await upload.run();

    expect(api.sign).toHaveBeenCalledWith('m1', null);
    expect(put.mock.calls.map((call) => call[0])).toEqual([
      'https://s3.test/one',
      'https://s3.test/fresh-one',
    ]);
  });

  it('retries the same link with growing pauses after a network drop', async () => {
    const api = fakeApi(planOf([null]));
    const results = [{ status: 0, etag: null }, { status: 503, etag: null }, ok('"e"')];
    const put = vi.fn<Put>(async () => results.shift() ?? ok('"e"'));
    const sleep = vi.fn(async (_ms: number) => {});
    const upload = new MediaUpload(new File(['abc'], 'a.jpg', { type: 'image/jpeg' }), 'job', {
      api,
      transport: { put },
      sleep,
    });

    await upload.run();

    expect(sleep.mock.calls.map((call) => call[0])).toEqual([1000, 2000]);
    expect(new Set(put.mock.calls.map((call) => call[0]))).toEqual(
      new Set(['https://s3.test/one']),
    );
    expect(api.sign).not.toHaveBeenCalled();
  });

  it('resumes only missing parts after it gave up', async () => {
    const api = fakeApi(planOf([1, 2], 4));
    let online = false;
    const put = vi.fn<Put>(async (url) =>
      url.endsWith('/2') && !online ? { status: 0, etag: null } : ok(`"${url}"`),
    );
    const { upload } = uploadOf(new File(['aaaabbbb'], 'v.mp4', { type: 'video/mp4' }), api, put);

    await expect(upload.run()).rejects.toBeInstanceOf(UploadFailedError);
    expect(put.mock.calls.filter((call) => call[0].endsWith('/2'))).toHaveLength(ATTEMPTS);
    online = true;
    put.mockClear();
    await upload.run();

    expect(api.start).toHaveBeenCalledOnce();
    expect(put.mock.calls.map((call) => call[0])).toEqual(['https://s3.test/2']);
    expect(api.complete.mock.calls[0]?.[1]).toHaveLength(2);
  });

  it('uploads again the parts the server did not find', async () => {
    const api = fakeApi(planOf([1, 2], 4));
    api.complete.mockRejectedValueOnce(
      new ApiError({
        type: 'about:blank',
        title: 'incomplete',
        status: 409,
        code: 'media_upload_incomplete',
        trace_id: null,
        missing_parts: [2],
      }),
    );
    const put = vi.fn<Put>(async (url) => ok(`"${url}"`));
    const { upload } = uploadOf(new File(['aaaabbbb'], 'v.mp4', { type: 'video/mp4' }), api, put);

    await expect(upload.run()).rejects.toBeInstanceOf(ApiError);
    put.mockClear();
    await upload.run();

    expect(put.mock.calls.map((call) => call[0])).toEqual(['https://s3.test/2']);
    expect(api.complete.mock.calls.at(-1)?.[1]).toHaveLength(2);
  });

  it('fails loudly when CORS hides the ETag of a part', async () => {
    const api = fakeApi(planOf([1, 2], 4));
    const put = vi.fn<Put>(async () => ({ status: 200, etag: null }));
    const { upload } = uploadOf(new File(['aaaabbbb'], 'v.mp4', { type: 'video/mp4' }), api, put);

    await expect(upload.run()).rejects.toThrow('ETag');
    expect(api.complete).not.toHaveBeenCalled();
  });

  it('stops sibling parts after one part fails for good', async () => {
    const api = fakeApi(planOf([1, 2, 3, 4], 4));
    const aborted: string[] = [];
    const put = vi.fn<Put>((url, _body, _headers, _progress, signal) =>
      url.endsWith('/1')
        ? Promise.resolve({ status: 200, etag: null }) // нет ETag — ошибка без повторов
        : new Promise<PutResult>((_resolve, reject) => {
            signal.addEventListener('abort', () => {
              aborted.push(url);
              reject(signal.reason as Error);
            });
          }),
    );
    const file = new File(['aaaabbbbccccdddd'], 'v.mp4', { type: 'video/mp4' });
    const { upload } = uploadOf(file, api, put);

    await expect(upload.run()).rejects.toThrow('ETag');
    expect(put.mock.calls.map((call) => call[0])).not.toContain('https://s3.test/4');
    expect(aborted.sort()).toEqual(['https://s3.test/2', 'https://s3.test/3']);
  });

  it('reports progress over all parts', async () => {
    const api = fakeApi(planOf([1, 2], 4));
    const put = vi.fn<Put>(async (url, body, _headers, progress) => {
      progress(body.size / 2);
      return ok(`"${url}"`);
    });
    const { upload, onProgress } = uploadOf(
      new File(['aaaabbbb'], 'v.mp4', { type: 'video/mp4' }),
      api,
      put,
    );

    await upload.run();

    const fractions = onProgress.mock.calls.map((call) => call[0] as number);
    expect(fractions[0]).toBe(0.25);
    expect(fractions.at(-1)).toBe(1);
  });

  it('shares one run between concurrent calls', async () => {
    const api = fakeApi(planOf([null]));
    const put = vi.fn<Put>(async () => ok('"e"'));
    const { upload } = uploadOf(new File(['abc'], 'a.jpg', { type: 'image/jpeg' }), api, put);

    await Promise.all([upload.run(), upload.run()]);

    expect(api.start).toHaveBeenCalledOnce();
    expect(api.complete).toHaveBeenCalledOnce();
  });

  it('cancel stops the transfer and deletes the record', async () => {
    const api = fakeApi(planOf([null]));
    let started!: () => void;
    const putStarted = new Promise<void>((resolve) => (started = resolve));
    const put = vi.fn<Put>(
      (_url, _body, _headers, _progress, signal) =>
        new Promise<PutResult>((_resolve, reject) => {
          started();
          signal.addEventListener('abort', () => reject(signal.reason as Error));
        }),
    );
    const { upload } = uploadOf(new File(['abc'], 'a.jpg', { type: 'image/jpeg' }), api, put);

    const run = upload.run();
    await putStarted;
    await upload.cancel();

    await expect(run).rejects.toBeInstanceOf(UploadCancelledError);
    expect(api.remove).toHaveBeenCalledWith('m1');
    await expect(upload.run()).rejects.toBeInstanceOf(UploadCancelledError);
    expect(api.start).toHaveBeenCalledOnce();
  });

  it('deletes the record that appears after cancel during start', async () => {
    const plan = planOf([null]);
    const api = fakeApi(plan);
    let answer!: (value: UploadOut) => void;
    api.start.mockImplementation(() => new Promise((resolve) => (answer = resolve)));
    const put = vi.fn<Put>(async () => ok('"e"'));
    const { upload } = uploadOf(new File(['abc'], 'a.jpg', { type: 'image/jpeg' }), api, put);

    const run = upload.run();
    await vi.waitFor(() => expect(api.start).toHaveBeenCalled());
    await upload.cancel();
    answer(plan);

    await expect(run).rejects.toBeInstanceOf(UploadCancelledError);
    expect(api.remove).toHaveBeenCalledWith('m1');
    expect(put).not.toHaveBeenCalled();
  });
});

describe('waitForMedia', () => {
  it('polls until processing ends', async () => {
    const api = fakeApi(planOf([null]));
    const statuses = ['processing', 'processing', 'ready'] as const;
    api.get.mockImplementation(async () =>
      media({ status: statuses[api.get.mock.calls.length - 1] }),
    );
    const sleep = vi.fn(async (_ms: number) => {});

    const result = await waitForMedia(media(), { api, sleep });

    expect(result.status).toBe('ready');
    expect(sleep.mock.calls.map((call) => call[0])).toEqual([1000, 2000, 3000]);
  });

  it('turns rejection into an error with the server answer', async () => {
    const api = fakeApi(planOf([null]));
    api.get.mockResolvedValue(media({ status: 'rejected' }));

    const wait = waitForMedia(media(), { api, sleep: noSleep });

    await expect(wait).rejects.toBeInstanceOf(MediaRejectedError);
    await expect(wait).rejects.toMatchObject({ media: { status: 'rejected' } });
  });

  it('gives up quietly: an uploaded file is not an error', async () => {
    const api = fakeApi(planOf([null]));
    api.get.mockResolvedValue(media({ status: 'uploaded' }));

    const result = await waitForMedia(media(), { api, sleep: noSleep, timeoutMs: 10_000 });

    expect(result.status).toBe('uploaded');
    // 1 + 2 + 3 + 5 = 11 с — четыре опроса до таймаута
    expect(api.get).toHaveBeenCalledTimes(4);
  });

  it('does not poll a file that is already settled', async () => {
    const api = fakeApi(planOf([null]));

    await waitForMedia(media({ status: 'ready' }), { api, sleep: noSleep });

    expect(api.get).not.toHaveBeenCalled();
  });

  it('stops when the screen is gone', async () => {
    const api = fakeApi(planOf([null]));
    const controller = new AbortController();
    const sleep = vi.fn(() => new Promise<void>(() => {}));

    const wait = waitForMedia(media(), { api, sleep, signal: controller.signal });
    controller.abort(new UploadCancelledError());

    await expect(wait).rejects.toBeInstanceOf(UploadCancelledError);
    expect(api.get).not.toHaveBeenCalled();
  });
});
