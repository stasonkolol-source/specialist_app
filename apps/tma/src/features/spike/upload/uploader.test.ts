import { describe, expect, it, vi } from 'vitest';

import type { Put, PutResult, SignedUrl, SpikeApi, UploadPlan } from './uploader.ts';
import { UploadFailedError, UploadTask, contentTypeOf } from './uploader.ts';

const signed = (part: number | null, url = `https://s3.test/${part ?? 'one'}`): SignedUrl => ({
  part_number: part,
  url,
  headers: part === null ? { 'Content-Type': 'image/jpeg' } : {},
  expires_at: '2026-09-27T12:00:00Z',
});

function fakeApi(plan: UploadPlan, size: number) {
  return {
    start: vi.fn(async () => plan),
    sign: vi.fn(async (body: { part_number: number | null }) =>
      signed(body.part_number, `https://s3.test/fresh-${body.part_number ?? 'one'}`),
    ),
    complete: vi.fn(async (_body: Parameters<SpikeApi['complete']>[0]) => undefined),
    abort: vi.fn(async () => undefined),
    head: vi.fn(async (key: string) => ({ key, size, content_type: null, etag: 'e', url: 'u' })),
  } satisfies SpikeApi;
}

const ok = (etag: string): PutResult => ({ status: 200, etag });
const deps = (api: SpikeApi, put: Put) => ({
  api,
  put,
  log: () => undefined,
  sleep: async () => {},
});

describe('spike uploader', () => {
  it('guesses HEIC type by extension when WebView gives none', () => {
    expect(contentTypeOf({ name: 'IMG_1.HEIC', type: '' })).toBe('image/heic');
    expect(contentTypeOf({ name: 'a.jpg', type: 'image/png' })).toBe('image/png');
  });

  it('puts a small file once and checks HEAD size', async () => {
    const file = new File(['abc'], 'a.jpg', { type: 'image/jpeg' });
    const api = fakeApi({ key: 'k', upload_id: null, part_size: 8, parts: [signed(null)] }, 3);
    const put = vi.fn<Put>(async () => ok('"e1"'));

    const { stored } = await new UploadTask(file, deps(api, put)).run(new AbortController().signal);

    expect(stored.size).toBe(3);
    expect(put).toHaveBeenCalledOnce();
    expect(put.mock.calls[0]?.[2]).toEqual({ 'Content-Type': 'image/jpeg' });
    expect(api.complete).not.toHaveBeenCalled();
  });

  it('slices multipart, re-signs an expired part and completes with ETags', async () => {
    const file = new File(['aaaabbbbcc'], 'v.mp4', { type: 'video/mp4' });
    const plan = { key: 'k', upload_id: 'u', part_size: 4, parts: [1, 2, 3].map((n) => signed(n)) };
    const api = fakeApi(plan, 10);
    const sizes: number[] = [];
    const put = vi.fn<Put>(async (url, body) => {
      sizes.push(body.size);
      return url === 'https://s3.test/2' ? { status: 400, etag: null } : ok(`"${url}"`);
    });

    await new UploadTask(file, deps(api, put)).run(new AbortController().signal);

    expect(sizes.sort()).toEqual([2, 4, 4, 4]);
    expect(api.sign).toHaveBeenCalledWith(expect.objectContaining({ part_number: 2, size: 4 }));
    const parts = api.complete.mock.calls[0]?.[0].parts;
    expect(parts?.map((p) => p.part_number).sort()).toEqual([1, 2, 3]);
    expect(parts?.find((p) => p.part_number === 2)?.etag).toBe('"https://s3.test/fresh-2"');
  });

  it('resumes only missing parts after a network failure', async () => {
    const file = new File(['aaaabbbb'], 'v.mp4', { type: 'video/mp4' });
    const plan = { key: 'k', upload_id: 'u', part_size: 4, parts: [1, 2].map((n) => signed(n)) };
    const api = fakeApi(plan, 8);
    let online = false;
    const put = vi.fn<Put>(async (url) =>
      url.endsWith('/2') && !online ? { status: 0, etag: null } : ok(`"${url}"`),
    );
    const task = new UploadTask(file, { ...deps(api, put), attempts: 2 });

    await expect(task.run(new AbortController().signal)).rejects.toBeInstanceOf(UploadFailedError);
    online = true;
    put.mockClear();
    await task.run(new AbortController().signal);

    expect(api.start).toHaveBeenCalledOnce();
    expect(put.mock.calls.map((call) => call[0])).toEqual(['https://s3.test/2']);
  });

  it('fails loudly when CORS hides ETag of a part', async () => {
    const file = new File(['aaaabbbb'], 'v.mp4', { type: 'video/mp4' });
    const plan = { key: 'k', upload_id: 'u', part_size: 4, parts: [1, 2].map((n) => signed(n)) };
    const put = vi.fn<Put>(async () => ({ status: 200, etag: null }));

    const run = new UploadTask(file, deps(fakeApi(plan, 8), put)).run(new AbortController().signal);

    await expect(run).rejects.toThrow('ETag');
  });

  it('stops sibling parts after one part fails for good', async () => {
    const file = new File(['aaaabbbbccccdddd'], 'v.mp4', { type: 'video/mp4' });
    const plan = {
      key: 'k',
      upload_id: 'u',
      part_size: 4,
      parts: [1, 2, 3, 4].map((n) => signed(n)),
    };
    const aborted: string[] = [];
    const put = vi.fn<Put>((url, _body, _headers, _progress, signal) =>
      url.endsWith('/1')
        ? Promise.resolve({ status: 200, etag: null }) // нет ETag — ошибка без повторов
        : new Promise<PutResult>((_resolve, reject) => {
            signal.addEventListener('abort', () => {
              aborted.push(url);
              reject(signal.reason);
            });
          }),
    );

    const run = new UploadTask(file, deps(fakeApi(plan, 16), put)).run(
      new AbortController().signal,
    );

    await expect(run).rejects.toThrow('ETag');
    expect(put.mock.calls.map((call) => call[0])).not.toContain('https://s3.test/4');
    expect(aborted.sort()).toEqual(['https://s3.test/2', 'https://s3.test/3']);
  });

  it('forgets the plan after cancel so retry starts a new upload', async () => {
    const file = new File(['aaaabbbb'], 'v.mp4', { type: 'video/mp4' });
    const plan = { key: 'k', upload_id: 'u', part_size: 4, parts: [1, 2].map((n) => signed(n)) };
    const api = fakeApi(plan, 8);
    const controller = new AbortController();
    const put = vi.fn<Put>(async (url) => {
      if (url.endsWith('/2')) controller.abort();
      return ok(`"${url}"`);
    });
    const task = new UploadTask(file, deps(api, put));

    await expect(task.run(controller.signal)).rejects.toThrow();
    await task.abort();
    await task.run(new AbortController().signal);

    expect(api.abort).toHaveBeenCalledWith({ key: 'k', upload_id: 'u' });
    expect(api.start).toHaveBeenCalledTimes(2);
    expect(api.complete.mock.calls.at(-1)?.[0].parts).toHaveLength(2);
  });
});
