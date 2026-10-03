import type { ResponseTemplateOut, ResponseTemplatesOut } from '@sosed/api-client';
import { configureApiClient } from '@sosed/api-client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook } from '@testing-library/react';
import type { ReactNode } from 'react';
import { describe, expect, it, vi } from 'vitest';

import {
  templatesQueryKey,
  useCreateTemplate,
  useDeleteTemplate,
  useResponseTemplates,
} from './templates.ts';

const template = (id: string, primary: boolean): ResponseTemplateOut => ({
  id,
  title: `Шаблон ${id}`,
  message: 'Здравствуйте! Могу сегодня.',
  price: { type: 'fixed', amount: { amount: 300_000, currency: 'RSD' } },
  availability_note: null,
  primary,
  updated_at: '2026-10-02T10:00:00Z',
});

const json = (body: unknown, status = 200) =>
  new Response(status === 204 ? null : JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });

/** Список шаблонов на экране, его перечитывание висит: видно, что мутация его не ждёт. */
function setup(items: ResponseTemplateOut[], answer: () => Response) {
  const fetch = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) =>
    (init?.method ?? 'GET') === 'GET' ? new Promise<Response>(() => undefined) : answer(),
  );
  configureApiClient({ fetch, locale: () => 'ru' });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  client.setQueryData<ResponseTemplatesOut>(templatesQueryKey(), { items, limit: 2 });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  const items_ = () => client.getQueryData<ResponseTemplatesOut>(templatesQueryKey())?.items;
  return { wrapper, items: items_ };
}

describe('response templates', () => {
  it('puts the created template into the list without waiting for the list GET', async () => {
    const created = template('t2', false);
    const { wrapper, items } = setup([template('t1', true)], () => json(created, 201));
    const { result } = renderHook(() => [useResponseTemplates(), useCreateTemplate()] as const, {
      wrapper,
    });

    await act(async () => {
      await result.current[1].mutateAsync({
        key: 'k1',
        body: {
          title: created.title,
          message: created.message,
          price_type: 'fixed',
          price_amount: 300_000,
        },
      });
    });

    expect(items()?.map((item) => item.id)).toEqual(['t1', 't2']);
  });

  it('makes the next template primary when the primary one is deleted', async () => {
    const { wrapper, items } = setup([template('t1', true), template('t2', false)], () =>
      json(null, 204),
    );
    const { result } = renderHook(() => [useResponseTemplates(), useDeleteTemplate()] as const, {
      wrapper,
    });

    await act(async () => {
      await result.current[1].mutateAsync('t1');
    });

    expect(items()).toEqual([{ ...template('t2', false), primary: true }]);
  });
});
