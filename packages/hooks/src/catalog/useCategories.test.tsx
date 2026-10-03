import type { CategoryOut } from '@sosed/api-client';
import { configureApiClient } from '@sosed/api-client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { describe, expect, it, vi } from 'vitest';

import { categoriesQueryKey, useCategories } from './categories.ts';

const SECTION: CategoryOut = {
  id: 1,
  slug: 'handyman',
  name: 'Мастер на час',
  icon: null,
  price_hint: null,
  tags: [],
  children: [],
};
const HINT = {
  min: { amount: 200_000, currency: 'RSD' },
  max: { amount: 400_000, currency: 'RSD' },
  unit: 'hour',
} as const;

describe('useCategories', () => {
  it('shows the cached tree at once and fills in the city price hints', async () => {
    let answer: () => void = () => undefined;
    const answered = new Promise<void>((resolve) => {
      answer = resolve;
    });
    const fetch = vi.fn(async (input: RequestInfo | URL) => {
      expect(new URL(String(input), 'http://api.test').searchParams.get('city')).toBe('novi-sad');
      await answered;
      return new Response(JSON.stringify([{ ...SECTION, price_hint: HINT }]), { status: 200 });
    });
    configureApiClient({ fetch, locale: () => 'ru' });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    // дерево без города уже в кэше (Главная, выдача)
    client.setQueryData(categoriesQueryKey('ru'), [SECTION]);
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );

    const { result } = renderHook(() => useCategories('ru', 'novi-sad'), { wrapper });

    // разделы видны сразу, ориентира цены ещё нет
    expect(result.current.data).toEqual([SECTION]);
    expect(result.current.isPlaceholderData).toBe(true);
    answer();
    await waitFor(() => expect(result.current.data?.[0]?.price_hint).toEqual(HINT));
    expect(fetch).toHaveBeenCalledOnce();
  });
});
