// Намерение перейти (app/intent.ts): палец на ссылке — данные экрана подробностей грузятся до
// нажатия, теми же ключами, что у экрана; ошибка такой предзагрузки не открывает экраны S49.
import { specialistCardQueryOptions } from '@sosed/hooks';
import { createMockPlatform } from '@sosed/platform/mock';
import { createMemoryHistory } from '@tanstack/react-router';
import { waitFor } from '@testing-library/react';
import { HttpResponse, http } from 'msw';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { useSystemStore } from '../features/service/s49-system/index.ts';
import { CARD_PROFILE_ID } from '../testing/fixtures.ts';
import { API_ORIGIN, server } from '../testing/msw.ts';
import { assemble } from './bootstrap.ts';
import { listenIntent, routeOf } from './intent.ts';

function touchLink(href: string) {
  const link = document.createElement('a');
  link.setAttribute('href', href);
  link.append(document.createElement('span'));
  document.body.append(link);
  link.firstElementChild?.dispatchEvent(new Event('pointerdown', { bubbles: true }));
  link.remove();
}

let stop: () => void = () => undefined;

function start() {
  const { platform } = createMockPlatform();
  const app = assemble(platform, {
    version: '0.1.0',
    history: createMemoryHistory({ initialEntries: ['/'] }),
    baseUrl: API_ORIGIN,
  });
  stop = listenIntent(app);
  return app;
}

beforeEach(() => useSystemStore.setState({ appWide: null, restriction: null }));
afterEach(() => stop());

describe('routeOf', () => {
  it('reads the route from browser and Telegram hash hrefs', () => {
    expect(routeOf('/specialists/1')).toBe('/specialists/1');
    expect(routeOf('/index.html?tgWebAppStartParam=x#/jobs/1?lat=1')).toBe('/jobs/1?lat=1');
    expect(routeOf('https://t.me/sosed')).toBeNull();
    expect(routeOf('//cdn.test/x')).toBeNull();
    expect(routeOf('#more')).toBeNull();
  });
});

describe('intent prefetch', () => {
  it('loads the profile when a finger lands on its card', async () => {
    const { queryClient } = start();
    const key = specialistCardQueryOptions(CARD_PROFILE_ID, 'ru').queryKey;

    touchLink(`/#/specialists/${CARD_PROFILE_ID}`);

    await waitFor(() => expect(queryClient.getQueryData(key)).toBeDefined());
  });

  it('keeps a failed prefetch silent: no maintenance screen from a link touch', async () => {
    server.use(
      http.get(`*/api/v1/specialists/${CARD_PROFILE_ID}`, () =>
        HttpResponse.json(
          { type: 'x', title: 'm', status: 503, code: 'maintenance', trace_id: null },
          { status: 503, headers: { 'Content-Type': 'application/problem+json' } },
        ),
      ),
    );
    const { queryClient } = start();
    const key = specialistCardQueryOptions(CARD_PROFILE_ID, 'ru').queryKey;

    touchLink(`/specialists/${CARD_PROFILE_ID}`);

    await waitFor(() => expect(queryClient.getQueryState(key)?.status).toBe('error'));
    expect(useSystemStore.getState().appWide).toBeNull();
  });
});
