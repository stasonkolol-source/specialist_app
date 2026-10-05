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

/** Конфиг первого запуска — без текстов (`?legal_documents=false`). */
const CONFIG: ClientConfigOut = {
  min_versions: {},
  flags: {},
  legal_versions: { terms: 'draft-1' },
  legal_documents: {},
  support_username: null,
};

function wrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
}

const NOT_FOUND = { status: 404, code: 'not_found' };

/** Ответы по адресу: client-config и /legal-documents; `null` — 404 (старый backend). */
function serve(config: unknown, documents: unknown) {
  const fetch = vi.fn(async (input: RequestInfo | URL) => {
    const body = String(input).startsWith('/api/v1/legal-documents') ? documents : config;
    return body === null
      ? new Response(JSON.stringify(NOT_FOUND), { status: 404 })
      : new Response(JSON.stringify(body), { status: 200 });
  });
  configureApiClient({ fetch });
  return fetch;
}

describe('useLegalDocument', () => {
  it('reads the text from its own request: the first launch config comes without texts', async () => {
    const fetch = serve(CONFIG, { documents: { terms: TERMS } });
    const { result } = renderHook(() => useLegalDocument('terms', 'ru'), { wrapper: wrapper() });

    await waitFor(() => expect(result.current.document).toEqual(TERMS));
    expect(result.current.text).toMatchObject({ title: 'Правила площадки', locale: 'ru' });
    const urls = fetch.mock.calls.map(([url]) => String(url));
    expect(urls).toContain('/api/v1/legal-documents');
    expect(urls).toContain('/api/v1/client-config?legal_documents=false');
  });

  it('falls back to the ru source without a translation', async () => {
    serve(CONFIG, { documents: { terms: TERMS } });
    const { result } = renderHook(() => useLegalDocument('terms', 'sr-Latn'), {
      wrapper: wrapper(),
    });

    await waitFor(() => expect(result.current.document).toEqual(TERMS));
    expect(result.current.text).toMatchObject({ title: 'Правила площадки', locale: 'ru' });
    expect(result.current.translated).toBe(false);
  });

  it('takes the texts from client-config of an older backend without /legal-documents', async () => {
    // фронтенд выкатили раньше backend: параметр он не знает и отдаёт тексты в конфиге
    serve({ ...CONFIG, legal_documents: { terms: TERMS } }, null);
    const { result } = renderHook(() => useLegalDocument('terms', 'ru'), { wrapper: wrapper() });

    await waitFor(() => expect(result.current.document).toEqual(TERMS));
    expect(result.current.text).toMatchObject({ title: 'Правила площадки' });
  });

  it('has no document when the backend sends no texts at all', async () => {
    // backend до 1.5a: ни /legal-documents, ни поля в конфиге
    serve({ min_versions: {}, flags: {}, legal_versions: { terms: 'draft-1' } }, null);
    const { result } = renderHook(() => useLegalDocument('terms', 'ru'), { wrapper: wrapper() });

    await waitFor(() => expect(result.current.query.isError).toBe(true));
    expect(result.current.document).toBeUndefined();
    expect(result.current.text).toBeNull();
  });
});
