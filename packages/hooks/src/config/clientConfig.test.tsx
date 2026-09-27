import type { ClientConfigOut } from '@sosed/api-client';
import { configureApiClient } from '@sosed/api-client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { describe, expect, it, vi } from 'vitest';

import { FLAGS, compareVersions, requiredUpdate, useFlag } from './clientConfig.ts';

const CONFIG: ClientConfigOut = {
  min_versions: { tma: '1.2.0' },
  flags: { 'goods.segment': true },
  legal_versions: {},
};

function wrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
}

const serve = (response: () => Response) => {
  const fetch = vi.fn(async () => response());
  configureApiClient({ fetch });
  return fetch;
};

describe('useFlag', () => {
  it('reads the flag from client-config', async () => {
    const fetch = serve(() => new Response(JSON.stringify(CONFIG), { status: 200 }));
    const { result } = renderHook(() => useFlag(FLAGS.goodsSegment), { wrapper: wrapper() });

    expect(result.current).toBe(false); // пока конфиг грузится — выключен
    await waitFor(() => expect(result.current).toBe(true));
    expect(fetch).toHaveBeenCalledWith('/api/v1/client-config', expect.anything());
  });

  it('is off when the flag is absent, false or config is unavailable', async () => {
    serve(() => new Response(JSON.stringify({ ...CONFIG, flags: {} }), { status: 200 }));
    const absent = renderHook(() => useFlag(FLAGS.goodsSegment), { wrapper: wrapper() });
    await waitFor(() => expect(absent.result.current).toBe(false));

    const fetch = serve(() => new Response('bad gateway', { status: 502 }));
    const failed = renderHook(() => useFlag(FLAGS.goodsSegment), { wrapper: wrapper() });
    await waitFor(() => expect(fetch).toHaveBeenCalled());
    expect(failed.result.current).toBe(false);
  });
});

describe('requiredUpdate', () => {
  it('asks to update Telegram below the minimum Bot API', () => {
    expect(requiredUpdate(CONFIG, { app: '1.2.0', telegram: '6.8' })).toBe('telegram');
    const custom = { ...CONFIG, min_versions: { ...CONFIG.min_versions, telegram: '8.0' } };
    expect(requiredUpdate(custom, { app: '1.2.0', telegram: '7.10' })).toBe('telegram');
    expect(requiredUpdate(custom, { app: '1.2.0', telegram: '9.1' })).toBeNull();
  });

  it('asks to reload an outdated Mini App bundle', () => {
    expect(requiredUpdate(CONFIG, { app: '1.1.9', telegram: '9.1' })).toBe('app');
    expect(requiredUpdate(CONFIG, { app: '1.10.0', telegram: '9.1' })).toBeNull();
  });

  it('does not check Telegram outside of it and tolerates a missing config', () => {
    expect(requiredUpdate(CONFIG, { app: '1.2.0', telegram: null })).toBeNull();
    expect(requiredUpdate(undefined, { app: '0.0.1', telegram: null })).toBeNull();
    expect(requiredUpdate(undefined, { app: '0.0.1', telegram: '6.0' })).toBe('telegram');
  });

  it('compares versions numerically', () => {
    expect(compareVersions('1.10', '1.9')).toBe(1);
    expect(compareVersions('7.0', '7')).toBe(0);
    expect(compareVersions('6.9', '7.0')).toBe(-1);
  });
});
