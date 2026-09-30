// Фейки API и плана загрузки для тестов media.
import type { MediaOut, SignedPartOut, UploadOut } from '@sosed/api-client';
import { vi } from 'vitest';

import type { MediaApi } from './upload.ts';

export const media = (overrides: Partial<MediaOut> = {}): MediaOut => ({
  id: 'm1',
  kind: 'image',
  purpose: 'portfolio',
  status: 'uploaded',
  mime_type: 'image/jpeg',
  size_bytes: 3,
  moderation_status: 'pending',
  created_at: '2026-09-29T12:00:00Z',
  uploaded_at: '2026-09-29T12:00:01Z',
  preview_url: null,
  width: null,
  height: null,
  duration_ms: null,
  placeholder: null,
  variants: [],
  video: null,
  failure_reason: null,
  ...overrides,
});

const signed = (part: number | null, url = `https://s3.test/${part ?? 'one'}`): SignedPartOut => ({
  part_number: part,
  url,
  headers: part === null ? { 'Content-Type': 'image/jpeg' } : {},
});

/** План одним PUT (`parts = [null]`) или multipart. */
export const planOf = (parts: (number | null)[], partSize: number | null = null): UploadOut => ({
  media_id: 'm1',
  multipart: parts[0] !== null,
  part_size: partSize,
  parts: parts.map((part) => signed(part)),
  expires_at: '2026-09-29T12:10:00Z',
});

export function fakeApi(plan: UploadOut, done: MediaOut = media()) {
  return {
    start: vi.fn(async () => plan),
    sign: vi.fn(async (_id: string, numbers: number[] | null) => ({
      ...plan,
      parts: (numbers ?? [null]).map((n) => signed(n, `https://s3.test/fresh-${n ?? 'one'}`)),
    })),
    complete: vi.fn(async (_id: string, _parts: { part_number: number; etag: string }[]) => done),
    get: vi.fn(async (_id: string) => media({ status: 'ready' })),
    remove: vi.fn(async (_id: string) => undefined),
  } satisfies MediaApi;
}
