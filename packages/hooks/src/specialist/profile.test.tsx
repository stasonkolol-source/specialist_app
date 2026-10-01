import type { ProfileOut } from '@sosed/api-client';
import { configureApiClient } from '@sosed/api-client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { describe, expect, it, vi } from 'vitest';

import { becomeStep, profileState, useMyProfile } from './profile.ts';

const DRAFT: ProfileOut = {
  id: '0199aa00-0000-7000-8000-000000000001',
  kind: 'pro',
  status: 'draft',
  display_name: 'Алексей М.',
  headline: null,
  about: null,
  languages: [],
  city_id: 1,
  category_ids: [],
  district_ids: [],
  travel_radius_km: null,
  work_modes: [],
  listed_in_catalog: true,
  rejection_reason: null,
  missing: ['category_ids', 'headline', 'work_modes', 'services'],
  completeness: { percent: 0, hints: [] },
  available_until: null,
  avatar: null,
  published_at: null,
  version: 1,
};

describe('becomeStep', () => {
  it('starts with the type when there is no profile yet', () => {
    expect(becomeStep(null)).toBe('type');
  });

  it('resumes a draft at the first step with something missing', () => {
    expect(becomeStep(DRAFT)).toBe('about');
    expect(becomeStep({ ...DRAFT, missing: ['area_ids', 'services'] })).toBe('area');
  });

  it('opens the last step of a complete draft: «Send for review» is there', () => {
    expect(becomeStep({ ...DRAFT, missing: [] })).toBe('area');
  });

  it('has no step once the profile is sent or published', () => {
    expect(becomeStep({ ...DRAFT, status: 'pending_review', missing: [] })).toBeNull();
    expect(becomeStep({ ...DRAFT, status: 'published', missing: [] })).toBeNull();
  });
});

describe('profileState', () => {
  it('tells a draft returned by moderation from a new one', () => {
    expect(profileState(DRAFT)).toBe('draft');
    expect(profileState({ ...DRAFT, rejection_reason: 'contacts_in_text' })).toBe('rejected');
    expect(profileState({ ...DRAFT, status: 'published' })).toBe('published');
  });
});

describe('useMyProfile', () => {
  const render = (response: () => Response) => {
    configureApiClient({ fetch: vi.fn(async () => response()), locale: () => 'ru' });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
    return renderHook(() => useMyProfile(), { wrapper });
  };

  it('reads 404 profile_not_found as «no profile yet», not as an error', async () => {
    const problem = {
      type: 'about:blank',
      title: 'Not found',
      status: 404,
      code: 'profile_not_found',
    };
    const { result } = render(
      () => new Response(JSON.stringify(problem), { status: 404, headers: { 'Content-Type': 'application/problem+json' } }),
    ); // prettier-ignore

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toBeNull();
  });

  it('returns the profile and keeps other failures as errors', async () => {
    const ok = render(() => new Response(JSON.stringify(DRAFT), { status: 200 }));
    await waitFor(() => expect(ok.result.current.data).toEqual(DRAFT));

    const problem = { type: 'about:blank', title: 'Error', status: 500, code: 'internal' };
    const failed = render(() => new Response(JSON.stringify(problem), { status: 500 }));
    await waitFor(() => expect(failed.result.current.isError).toBe(true));
  });
});
