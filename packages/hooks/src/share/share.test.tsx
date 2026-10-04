import type { ShareOut } from '@sosed/api-client';
import { configureApiClient } from '@sosed/api-client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { describe, expect, it, vi } from 'vitest';

import type { ShareChannel, ShareOutcome } from './share.ts';
import { shareVia, useShare } from './share.ts';

const OUT: ShareOut = {
  url: 'https://t.me/sosed_test_bot?startapp=s_4bN8wE2rT6yU1iO3pA5sDf_rAB12CD34',
  start_param: 's_4bN8wE2rT6yU1iO3pA5sDf_rAB12CD34',
  text: 'Алексей М.',
  prepared_message_id: 'prepared-1',
};

function channel(shareMessage: boolean, link: ShareOutcome = 'shared') {
  return {
    capabilities: { shareMessage },
    shareMessage: vi.fn(async () => false),
    shareLink: vi.fn(async () => link),
  } satisfies ShareChannel;
}

describe('shareVia', () => {
  it('карточка — в выбор чата; закрытое окно ссылкой не дублируется', async () => {
    const telegram = channel(true);
    expect(await shareVia(telegram, OUT)).toBe('shared');
    expect(telegram.shareMessage).toHaveBeenCalledWith('prepared-1');
    expect(telegram.shareLink).not.toHaveBeenCalled();
  });

  it('карточки нет или клиент старый — ссылка с подписью', async () => {
    const old = channel(false);
    await shareVia(old, OUT);
    expect(old.shareLink).toHaveBeenCalledWith(OUT.url, 'Алексей М.');
    const noCard = channel(true, 'copied');
    expect(await shareVia(noCard, { ...OUT, prepared_message_id: null })).toBe('copied');
    expect(noCard.shareMessage).not.toHaveBeenCalled();
  });
});

describe('useShare', () => {
  function setup(platform: ShareChannel, status = 200) {
    const fetch = vi.fn(async () => Response.json(OUT, { status }));
    configureApiClient({ fetch, locale: () => 'ru' });
    const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
    return { fetch, ...renderHook(() => useShare(platform), { wrapper }) };
  }

  it('POST /share по нажатию; скопированная ссылка — тост', async () => {
    const browser = channel(false, 'copied');
    const { fetch, result } = setup(browser);
    act(() => result.current.share({ type: 'specialist', id: 'p1' }));
    await waitFor(() => expect(result.current.copied).toBe(true));
    const [url, init] = fetch.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toMatch(/\/share$/);
    expect(JSON.parse(String(init.body))).toEqual({ entity_type: 'specialist', entity_id: 'p1' });
    expect(result.current.failed).toBe(false);
  });

  it('ссылку не дали (скрыли, нет сети) — ошибка, платформу не зовём', async () => {
    const telegram = channel(true);
    const { result } = setup(telegram, 404);
    act(() => result.current.share({ type: 'job', id: 'j1' }));
    await waitFor(() => expect(result.current.failed).toBe(true));
    expect(telegram.shareMessage).not.toHaveBeenCalled();
    expect(telegram.shareLink).not.toHaveBeenCalled();
  });
});
