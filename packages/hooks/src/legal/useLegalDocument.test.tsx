import type { ClientConfigOut, LegalDocumentOut } from '@sosed/api-client';
import { configureApiClient } from '@sosed/api-client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { describe, expect, it, vi } from 'vitest';

import { useLegalDocument } from './useLegalDocument.ts';

const TERMS: LegalDocumentOut = {
  version: 'draft-1',
  published_on: '2026-09-27',
  texts: { ru: { title: 'Правила площадки', body: 'Текст.\n' } },
};

const CONFIG: ClientConfigOut = {
  min_versions: {},
  flags: {},
  legal_versions: { terms: 'draft-1' },
  legal_documents: { terms: TERMS },
  support_username: null,
};

function wrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
}

const serve = (body: unknown) =>
  configureApiClient({
    fetch: vi.fn(async () => new Response(JSON.stringify(body), { status: 200 })),
  });

describe('useLegalDocument', () => {
  it('falls back to the ru source without a translation', async () => {
    serve(CONFIG);
    const { result } = renderHook(() => useLegalDocument('terms', 'sr-Latn'), {
      wrapper: wrapper(),
    });

    await waitFor(() => expect(result.current.document).toEqual(TERMS));
    expect(result.current.text).toMatchObject({ title: 'Правила площадки', locale: 'ru' });
    expect(result.current.translated).toBe(false);
  });

  it('has no document when the backend does not send legal_documents yet', async () => {
    // фронтенд выкатили раньше backend 1.5a или backend откатили: поля в ответе нет
    serve({ min_versions: {}, flags: {}, legal_versions: { terms: 'draft-1' } });
    const { result } = renderHook(() => useLegalDocument('terms', 'ru'), { wrapper: wrapper() });

    await waitFor(() => expect(result.current.config.isSuccess).toBe(true));
    expect(result.current.document).toBeUndefined();
    expect(result.current.text).toBeNull();
  });
});
