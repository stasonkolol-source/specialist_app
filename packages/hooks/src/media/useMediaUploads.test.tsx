import { ApiError, NetworkError, RateLimitedError } from '@sosed/api-client';
import { act, renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { fakeApi, media, planOf } from './testing.ts';
import type { MediaTransport, PutResult } from './upload.ts';
import { MediaRejectedError } from './upload.ts';
import { UPLOADS_AT_ONCE, isRetryable, useMediaUploads } from './useMediaUploads.ts';

type Put = MediaTransport['put'];

const photo = (name = 'a.jpg') => new File(['abc'], name, { type: 'image/jpeg' });
const ok: PutResult = { status: 200, etag: '"e"' };
const noSleep = async () => {};
const problem = (status: number, code: string) =>
  new ApiError({ type: 'about:blank', title: code, status, code, trace_id: null });

function setup(put: Put, options: { max?: number; prepare?: MediaTransport['prepare'] } = {}) {
  const api = fakeApi(planOf([null]));
  const transport: MediaTransport = {
    put,
    ...(options.prepare ? { prepare: options.prepare } : {}),
  };
  const hook = renderHook(() =>
    useMediaUploads({
      purpose: 'job',
      transport,
      api,
      sleep: noSleep,
      pollTimeoutMs: 0,
      ...(options.max === undefined ? {} : { max: options.max }),
    }),
  );
  return { api, ...hook };
}

describe('useMediaUploads', () => {
  it('uploads added files and hands their ids to the form', async () => {
    const thumb = new Blob(['t']);
    const prepare = vi.fn(async (file: Blob) => ({ body: file, preview: thumb }));
    const { result, api } = setup(
      vi.fn<Put>(async () => ok),
      { prepare },
    );

    act(() => {
      result.current.add([photo()]);
    });
    expect(result.current.items[0]).toMatchObject({ status: 'uploading', progress: 0 });
    expect(result.current.uploading).toBe(true);

    await waitFor(() => expect(result.current.items[0]?.status).toBe('uploaded'));
    expect(result.current.items[0]).toMatchObject({ progress: 1, preview: thumb, error: null });
    expect(result.current.mediaIds).toEqual(['m1']);
    expect(result.current.uploading).toBe(false);
    expect(api.start).toHaveBeenCalledWith(
      expect.objectContaining({ purpose: 'job' }),
      expect.any(String),
    );
  });

  it(`sends at most ${UPLOADS_AT_ONCE} files at once`, async () => {
    let active = 0;
    let peak = 0;
    const put = vi.fn<Put>(async () => {
      active += 1;
      peak = Math.max(peak, active);
      await new Promise((resolve) => setTimeout(resolve, 5));
      active -= 1;
      return ok;
    });
    const { result } = setup(put);

    act(() => {
      result.current.add([photo('1.jpg'), photo('2.jpg'), photo('3.jpg'), photo('4.jpg')]);
    });

    await waitFor(() =>
      expect(result.current.items.every((item) => item.status === 'uploaded')).toBe(true),
    );
    expect(put).toHaveBeenCalledTimes(4);
    expect(peak).toBe(UPLOADS_AT_ONCE);
  });

  it('lets the user retry a transfer that failed and resumes it', async () => {
    let online = false;
    const put = vi.fn<Put>(async () => (online ? ok : { status: 0, etag: null }));
    const { result, api } = setup(put);

    act(() => {
      result.current.add([photo()]);
    });
    await waitFor(() => expect(result.current.items[0]?.status).toBe('failed'));
    expect(result.current.items[0]?.retryable).toBe(true);

    online = true;
    act(() => result.current.retry('upload-1'));
    await waitFor(() => expect(result.current.items[0]?.status).toBe('uploaded'));
    expect(api.start).toHaveBeenCalledOnce();
  });

  it('does not offer retry for a file the server refused', async () => {
    const { result, api } = setup(vi.fn<Put>(async () => ok));
    api.start.mockRejectedValue(problem(422, 'media_too_large'));

    act(() => {
      result.current.add([photo()]);
    });
    await waitFor(() => expect(result.current.items[0]?.status).toBe('failed'));
    expect(result.current.items[0]?.retryable).toBe(false);

    act(() => result.current.retry('upload-1'));
    expect(api.start).toHaveBeenCalledOnce();
  });

  it('marks a file rejected by processing as failed for good', async () => {
    const api = fakeApi(planOf([null]));
    api.get.mockResolvedValue(media({ status: 'rejected' }));
    const { result } = renderHook(() =>
      useMediaUploads({ purpose: 'job', transport: { put: async () => ok }, api, sleep: noSleep }),
    );

    act(() => {
      result.current.add([photo()]);
    });

    await waitFor(() => expect(result.current.items[0]?.status).toBe('failed'));
    expect(result.current.items[0]).toMatchObject({
      retryable: false,
      media: { status: 'rejected' },
    });
    expect(result.current.items[0]?.error).toBeInstanceOf(MediaRejectedError);
    expect(result.current.mediaIds).toEqual([]);
  });

  it('removing a file stops it and deletes the record', async () => {
    const put = vi.fn<Put>(
      (_url, _body, _headers, _progress, signal) =>
        new Promise<PutResult>((_resolve, reject) => {
          signal.addEventListener('abort', () => reject(signal.reason as Error));
        }),
    );
    const { result, api } = setup(put);

    act(() => {
      result.current.add([photo()]);
    });
    await waitFor(() => expect(put).toHaveBeenCalled());
    act(() => result.current.remove('upload-1'));

    expect(result.current.items).toEqual([]);
    await waitFor(() => expect(api.remove).toHaveBeenCalledWith('m1'));
  });

  it('removing an uploaded file deletes it on the server too', async () => {
    const { result, api } = setup(vi.fn<Put>(async () => ok));

    act(() => {
      result.current.add([photo()]);
    });
    await waitFor(() => expect(result.current.items[0]?.status).toBe('uploaded'));
    act(() => result.current.remove('upload-1'));

    await waitFor(() => expect(api.remove).toHaveBeenCalledWith('m1'));
    expect(result.current.mediaIds).toEqual([]);
  });

  it('reset forgets files the form has sent without deleting them', async () => {
    const { result, api } = setup(vi.fn<Put>(async () => ok));

    act(() => {
      result.current.add([photo()]);
    });
    await waitFor(() => expect(result.current.items[0]?.status).toBe('uploaded'));
    act(() => result.current.reset());

    expect(result.current.items).toEqual([]);
    expect(api.remove).not.toHaveBeenCalled();
  });

  it('forget drops an attached file without deleting it, but not one still uploading', async () => {
    let release: (result: PutResult) => void = () => {};
    const put = vi
      .fn<Put>(async () => ok)
      .mockImplementationOnce(async () => ok)
      .mockImplementationOnce(() => new Promise<PutResult>((resolve) => (release = resolve)));
    const { result, api } = setup(put);

    act(() => {
      result.current.add([photo('1.jpg'), photo('2.jpg')]);
    });
    await waitFor(() => expect(result.current.items[0]?.status).toBe('uploaded'));
    act(() => {
      result.current.forget('upload-1');
      result.current.forget('upload-2');
    });

    expect(result.current.items.map((item) => item.key)).toEqual(['upload-2']);
    act(() => release(ok));
    await waitFor(() => expect(result.current.items[0]?.status).toBe('uploaded'));
    expect(api.remove).not.toHaveBeenCalled();
  });

  it('keeps within the limit and says how many did not fit', () => {
    const { result } = setup(
      vi.fn<Put>(() => new Promise<PutResult>(() => {})),
      { max: 2 },
    );

    let skipped = 0;
    act(() => {
      skipped = result.current.add([photo('1.jpg'), photo('2.jpg'), photo('3.jpg')]);
    });

    expect(skipped).toBe(1);
    expect(result.current.items).toHaveLength(2);
    act(() => {
      skipped = result.current.add([photo('4.jpg')]);
    });
    expect(skipped).toBe(1);
  });

  it('leaving the screen stops unfinished uploads', async () => {
    const put = vi.fn<Put>(
      (_url, _body, _headers, _progress, signal) =>
        new Promise<PutResult>((_resolve, reject) => {
          signal.addEventListener('abort', () => reject(signal.reason as Error));
        }),
    );
    const { result, api, unmount } = setup(put);

    act(() => {
      result.current.add([photo()]);
    });
    await waitFor(() => expect(put).toHaveBeenCalled());
    unmount();

    await waitFor(() => expect(api.remove).toHaveBeenCalledWith('m1'));
  });
});

describe('isRetryable', () => {
  it('retries the network, the server and limits, not the file itself', () => {
    expect(isRetryable(new NetworkError('offline'))).toBe(true);
    expect(isRetryable(problem(503, 'external_service_unavailable'))).toBe(true);
    expect(
      isRetryable(
        new RateLimitedError(
          { type: 'about:blank', title: 'x', status: 429, code: 'rate_limited', trace_id: null },
          60,
        ),
      ),
    ).toBe(true);
    expect(isRetryable(problem(409, 'idempotency_in_progress'))).toBe(true);
    expect(isRetryable(problem(422, 'media_type_not_allowed'))).toBe(false);
    expect(isRetryable(new MediaRejectedError(media({ status: 'rejected' })))).toBe(false);
  });
});
