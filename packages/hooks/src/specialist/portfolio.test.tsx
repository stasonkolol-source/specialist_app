import type { MediaRefOut, PortfolioOut, WorkOut } from '@sosed/api-client';
import { configureApiClient, getSpecialistsGetMyPortfolioQueryKey } from '@sosed/api-client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { describe, expect, it, vi } from 'vitest';

import { fakeApi, planOf } from '../media/testing.ts';
import type { MediaTransport } from '../media/upload.ts';
import {
  broken,
  fitFiles,
  hiddenByModerator,
  onReview,
  portfolioRoom,
  processing,
  usePortfolioUploads,
  workKindOf,
} from './portfolio.ts';

const LIMITS = { image: 60, video: 6 };
const file = (type: string) => ({ type });

describe('portfolio room', () => {
  it('treats mp4 and mov as videos and the rest as photos', () => {
    expect(workKindOf(file('video/quicktime'))).toBe('video');
    expect(workKindOf(file('image/heic'))).toBe('image');
    expect(workKindOf(file(''))).toBe('image');
  });

  it('counts finished works and files still uploading', () => {
    const works = [...Array(58).fill({ kind: 'image' }), ...Array(5).fill({ kind: 'video' })];

    expect(portfolioRoom(works, LIMITS, [file('image/jpeg')])).toEqual({ image: 1, video: 1 });
    expect(portfolioRoom(works, LIMITS, [file('video/mp4'), file('video/mp4')])).toEqual({
      image: 2,
      video: 0,
    });
  });

  it('keeps the files that fit, in the order they were chosen', () => {
    const chosen = [file('video/mp4'), file('image/png'), file('video/mp4'), file('image/jpeg')];

    const { accepted, skipped } = fitFiles(chosen, { image: 1, video: 1 });

    expect(accepted).toEqual([file('video/mp4'), file('image/png')]);
    expect(skipped).toBe(2);
  });
});

const mediaRef = (overrides: Partial<MediaRefOut> = {}): MediaRefOut => ({
  id: 'media-1',
  kind: 'image',
  status: 'ready',
  placeholder: null,
  variants: [],
  video_url: null,
  duration_ms: null,
  ...overrides,
});

const work = (id: string, overrides: Partial<WorkOut> = {}): WorkOut => ({
  id,
  kind: 'image',
  caption: null,
  position: 0,
  media: mediaRef({ id: `media-${id}` }),
  status: 'published',
  ...overrides,
});

describe('work state', () => {
  it('tells a file still processing from one that failed processing', () => {
    const at = (status: string) => ({ media: mediaRef({ status }) });
    expect(processing(at('uploaded'))).toBe(true);
    expect(processing(at('processing'))).toBe(true);
    expect(processing(at('ready'))).toBe(false);
    expect(broken(at('rejected'))).toBe(true);
    expect(broken(at('ready'))).toBe(false);
    expect(broken({ media: null })).toBe(false);
  });

  it('tells a work on review from a published or hidden one', () => {
    expect(onReview({ status: 'pending' })).toBe(true);
    expect(onReview({ status: 'published' })).toBe(false);
    expect(hiddenByModerator({ status: 'rejected' })).toBe(true);
    expect(hiddenByModerator({ status: 'pending' })).toBe(false);
  });
});

const photo = (name = 'a.jpg') => new File(['abc'], name, { type: 'image/jpeg' });
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': status >= 400 ? 'application/problem+json' : 'application/json' },
  });
const problem = (status: number, code: string) =>
  json({ type: 'about:blank', title: code, status, code, trace_id: null }, status);

/** Ответ «сервера» на запрос; `method` — чтобы отличать прикрепление от чтения портфолио. */
type Reply = (method: string) => Response;

function setup(portfolio: PortfolioOut, reply: Reply) {
  const sent: { url: string; key: string | null; body: unknown }[] = [];
  configureApiClient({
    locale: () => 'ru',
    sleep: async () => {},
    fetch: vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const method = init?.method ?? 'GET';
      if (method !== 'GET') {
        sent.push({
          url: String(input),
          key: new Headers(init?.headers).get('Idempotency-Key'),
          body: JSON.parse(String(init?.body)),
        });
      }
      return reply(method);
    }),
  });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const key = getSpecialistsGetMyPortfolioQueryKey();
  client.setQueryData(key, portfolio);
  const thumb = new Blob(['t']);
  const transport: MediaTransport = {
    put: async () => ({ status: 200, etag: '"e"' }),
    prepare: async (body) => ({ body, preview: thumb }),
  };
  const api = fakeApi(planOf([null]));
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  const hook = renderHook(
    () =>
      usePortfolioUploads(client.getQueryData<PortfolioOut>(key), {
        transport,
        api,
        sleep: async () => {},
      }),
    { wrapper },
  );
  const works = () => client.getQueryData<PortfolioOut>(key)?.items.map((item) => item.id);
  return { ...hook, api, sent, thumb, works };
}

describe('usePortfolioUploads', () => {
  it('attaches an uploaded file as a work at the end and keeps its preview', async () => {
    const added = work('w2', { position: 1, media: mediaRef({ id: 'm1', status: 'processing' }) });
    const { result, sent, thumb, works } = setup({ items: [work('w1')], limits: LIMITS }, () =>
      json(added, 201),
    );

    let skipped = -1;
    act(() => {
      skipped = result.current.add([photo()]);
    });
    expect(skipped).toBe(0);

    await waitFor(() => expect(result.current.items).toEqual([]));
    expect(sent).toEqual([
      { url: '/api/v1/me/profile/portfolio', key: 'portfolio-m1', body: { media_id: 'm1' } },
    ]);
    expect(works()).toEqual(['w1', 'w2']);
    expect(result.current.previews.get('m1')).toBe(thumb);
  });

  it('does not start files over the limits and says how many were skipped', () => {
    const full = { items: [work('w1')], limits: { image: 1, video: 6 } };
    const { result, api } = setup(full, () => json({}));

    let skipped = 0;
    act(() => {
      skipped = result.current.add([photo('1.jpg'), photo('2.jpg')]);
    });

    expect(skipped).toBe(2);
    expect(result.current.items).toEqual([]);
    expect(api.start).not.toHaveBeenCalled();
  });

  it('keeps a file that did not attach and attaches it again on retry', async () => {
    let online = false;
    const { result, works } = setup({ items: [], limits: LIMITS }, () =>
      online ? json(work('w1'), 201) : problem(503, 'service_unavailable'),
    );

    act(() => {
      result.current.add([photo()]);
    });
    await waitFor(() => expect(result.current.items[0]?.status).toBe('failed'));
    expect(result.current.items[0]?.retryable).toBe(true);

    online = true;
    act(() => result.current.retry('upload-1'));

    await waitFor(() => expect(result.current.items).toEqual([]));
    expect(works()).toEqual(['w1']);
  });

  it('keeps the file when the work was created but its answer was lost', async () => {
    const created = work('w1', { media: mediaRef({ id: 'm1', status: 'processing' }) });
    const { result, api, works } = setup({ items: [], limits: LIMITS }, (method) =>
      method === 'GET'
        ? json({ items: [created], limits: LIMITS })
        : problem(504, 'gateway_timeout'),
    );

    act(() => {
      result.current.add([photo()]);
    });
    await waitFor(() => expect(result.current.items[0]?.status).toBe('failed'));
    act(() => result.current.remove('upload-1'));

    await waitFor(() => expect(result.current.items).toEqual([]));
    expect(works()).toEqual(['w1']);
    expect(api.remove).not.toHaveBeenCalled();
  });

  it('offers only removal when the portfolio is already full', async () => {
    const { result, api } = setup({ items: [], limits: LIMITS }, (method) =>
      method === 'GET' ? json({ items: [], limits: LIMITS }) : problem(409, 'portfolio_full'),
    );

    act(() => {
      result.current.add([photo()]);
    });
    await waitFor(() => expect(result.current.items[0]?.status).toBe('failed'));
    expect(result.current.items[0]?.retryable).toBe(false);

    act(() => result.current.remove('upload-1'));
    // работы с этим файлом на сервере нет — файл удаляется
    await waitFor(() => expect(result.current.items).toEqual([]));
    await waitFor(() => expect(api.remove).toHaveBeenCalledWith('m1'));
  });
});
