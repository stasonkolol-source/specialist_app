import type { CityOut } from '@sosed/api-client';
import { configureApiClient } from '@sosed/api-client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { describe, expect, it, vi } from 'vitest';

import { citiesQueryKey, defaultCity, useCities } from './cities.ts';

const city = (id: number, name: string, status: CityOut['status']): CityOut => ({
  id,
  slug: `c${id}`,
  name,
  status,
  center: { lat: 45.2671, lon: 19.8335 },
});

const NOVI_SAD = city(1, 'Нови-Сад', 'active');
const BELGRADE = city(2, 'Белград', 'soon');

describe('defaultCity', () => {
  it('keeps the chosen city while it is active', () => {
    const cities = [NOVI_SAD, city(3, 'Ниш', 'active'), BELGRADE];
    expect(defaultCity(cities, 3)).toBe(3);
  });

  it('falls back to the first active city: «soon» cannot be chosen', () => {
    expect(defaultCity([BELGRADE, NOVI_SAD], null)).toBe(1);
    expect(defaultCity([BELGRADE, NOVI_SAD], 2)).toBe(1);
    expect(defaultCity([BELGRADE], null)).toBeNull();
  });
});

describe('useCities', () => {
  it('keys the list by language: names come in the language of the request', async () => {
    let language = 'ru';
    const fetch = vi.fn(async (_url: RequestInfo | URL, init?: RequestInit) => {
      const header = new Headers(init?.headers).get('Accept-Language');
      const name = header === 'sr-Latn' ? 'Novi Sad' : 'Нови-Сад';
      return new Response(JSON.stringify([{ ...NOVI_SAD, name }]), { status: 200 });
    });
    configureApiClient({ fetch, locale: () => language });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );

    const { result, rerender } = renderHook(({ locale }) => useCities(locale), {
      wrapper,
      initialProps: { locale: 'ru' as const as 'ru' | 'sr-Latn' },
    });
    await waitFor(() => expect(result.current.data?.[0]?.name).toBe('Нови-Сад'));

    language = 'sr-Latn';
    rerender({ locale: 'sr-Latn' });
    // до ответа — прежний список, а не скелетон
    expect(result.current.data?.[0]?.name).toBe('Нови-Сад');
    await waitFor(() => expect(result.current.data?.[0]?.name).toBe('Novi Sad'));
    expect(client.getQueryData(citiesQueryKey('ru'))).toHaveLength(1);
  });
});
