import type { ClientConfigOut, LegalDocumentOut, ProblemOut } from '@sosed/api-client';
import {
  ApiError,
  MaintenanceError,
  NetworkError,
  RateLimitedError,
  RestrictedError,
  UpgradeRequiredError,
  configureApiClient,
} from '@sosed/api-client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { describe, expect, it, vi } from 'vitest';

import { isLegalDocument, legalText, useLegalDocument } from '../legal/useLegalDocument.ts';
import { isAppWide, startupState, systemStateOf } from './systemState.ts';

const problem = (status: number, code: string, extra: Partial<ProblemOut> = {}): ProblemOut => ({
  type: 'x',
  title: 't',
  status,
  code,
  trace_id: 'trace-1',
  ...extra,
});

describe('systemStateOf', () => {
  it('maps api-client errors to S49 states', () => {
    expect(systemStateOf(new NetworkError('offline'))).toEqual({ kind: 'offline' });
    expect(systemStateOf(new MaintenanceError(problem(503, 'maintenance'), 120))).toEqual({
      kind: 'maintenance',
    });
    expect(
      systemStateOf(new UpgradeRequiredError(problem(426, 'client_upgrade_required'))),
    ).toEqual({ kind: 'update', target: 'app' });
    expect(systemStateOf(new ApiError(problem(500, 'internal_error')))).toEqual({
      kind: 'error',
      traceId: 'trace-1',
    });
    expect(systemStateOf(new RateLimitedError(problem(429, 'rate_limited'), 60))).toMatchObject({
      kind: 'error',
    });
    expect(systemStateOf(new TypeError('render'))).toEqual({ kind: 'error', traceId: null });
  });

  it('tells partial restrictions from account-blocking ones', () => {
    const until = '2026-10-03T16:00:00Z';
    const posting = systemStateOf(
      new RestrictedError(problem(403, 'restricted', { restriction: 'posting_blocked', until })),
    );
    expect(posting).toEqual({
      kind: 'restricted',
      restriction: 'posting_blocked',
      until: new Date(until),
      blocking: false,
    });
    expect(isAppWide(posting)).toBe(false);
    const banned = systemStateOf(
      new RestrictedError(problem(403, 'restricted', { restriction: 'banned' })),
    );
    expect(banned).toMatchObject({ restriction: 'banned', until: null, blocking: true });
    expect(isAppWide(banned)).toBe(true);
    expect(
      systemStateOf(
        new RestrictedError(problem(403, 'restricted', { restriction: 'future_kind' })),
      ),
    ).toMatchObject({ restriction: null, blocking: false });
  });

  it('keeps offline and errors screen-level', () => {
    expect(isAppWide({ kind: 'offline' })).toBe(false);
    expect(isAppWide({ kind: 'error', traceId: null })).toBe(false);
    expect(isAppWide({ kind: 'maintenance' })).toBe(true);
    expect(isAppWide({ kind: 'update', target: 'telegram' })).toBe(true);
  });
});

describe('startupState', () => {
  const config: ClientConfigOut = {
    min_versions: { tma: '1.0.0' },
    flags: { 'platform.maintenance': true },
    legal_versions: {},
    legal_documents: {},
  };

  it('puts the update before maintenance', () => {
    expect(startupState(config, { app: '0.9.0', telegram: '9.1' })).toEqual({
      kind: 'update',
      target: 'app',
    });
    expect(startupState(config, { app: '1.0.0', telegram: '6.0' })).toEqual({
      kind: 'update',
      target: 'telegram',
    });
    expect(startupState(config, { app: '1.0.0', telegram: '9.1' })).toEqual({
      kind: 'maintenance',
    });
    const open = { ...config, flags: { 'platform.maintenance': false } };
    expect(startupState(open, { app: '1.0.0', telegram: null })).toBeNull();
    expect(startupState(undefined, { app: '1.0.0', telegram: null })).toBeNull();
  });
});

const TERMS: LegalDocumentOut = {
  version: 'draft-1',
  published_on: '2026-09-27',
  texts: { ru: { title: 'Правила площадки «Соседи»', body: 'Текст.\n' } },
};

describe('legalText', () => {
  it('takes the interface language and falls back to the Russian source', () => {
    const translated: LegalDocumentOut = {
      ...TERMS,
      texts: {
        ...TERMS.texts,
        'sr-Latn': { title: 'Pravila platforme „Sosedi“', body: 'Tekst.\n' },
      },
    };
    expect(legalText(translated, 'sr-Latn')).toEqual({
      locale: 'sr-Latn',
      title: 'Pravila platforme „Sosedi“',
      body: 'Tekst.\n',
    });
    expect(legalText(translated, 'sr-Cyrl')?.locale).toBe('ru');
    expect(legalText({ ...TERMS, texts: {} }, 'ru')).toBeNull();
  });

  it('knows the S48 documents', () => {
    expect(isLegalDocument('terms')).toBe(true);
    expect(isLegalDocument('privacy')).toBe(true);
    expect(isLegalDocument('moderation')).toBe(false);
  });
});

describe('useLegalDocument', () => {
  function wrapper() {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
  }

  it('reads the current edition from client-config and flags a missing translation', async () => {
    const config: ClientConfigOut = {
      min_versions: {},
      flags: {},
      legal_versions: { terms: 'draft-1' },
      legal_documents: { terms: TERMS },
    };
    const fetch = vi.fn(async () => new Response(JSON.stringify(config), { status: 200 }));
    configureApiClient({ fetch });

    const { result } = renderHook(() => useLegalDocument('terms', 'sr-Latn'), {
      wrapper: wrapper(),
    });

    await waitFor(() => expect(result.current.document).toEqual(TERMS));
    expect(result.current.text).toMatchObject({ locale: 'ru', title: 'Правила площадки «Соседи»' });
    expect(result.current.translated).toBe(false);
    // тексты — в том же client-config: отдельного запроса нет
    expect(fetch).toHaveBeenCalledOnce();
    expect(fetch).toHaveBeenCalledWith('/api/v1/client-config', expect.anything());
  });

  it('has no document when its version has no text', async () => {
    const config: ClientConfigOut = {
      min_versions: {},
      flags: {},
      legal_versions: { privacy: 'draft-9' },
      legal_documents: {},
    };
    configureApiClient({
      fetch: vi.fn(async () => new Response(JSON.stringify(config), { status: 200 })),
    });

    const { result } = renderHook(() => useLegalDocument('privacy', 'ru'), { wrapper: wrapper() });

    await waitFor(() => expect(result.current.config.isSuccess).toBe(true));
    expect(result.current.document).toBeUndefined();
    expect(result.current.text).toBeNull();
    expect(result.current.translated).toBe(true);
  });
});
