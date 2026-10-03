// Запуск до React (app/startup.ts): конфиг и справочники Главной запрашиваются сразу после сборки,
// данные Главной — как только вход решил город. Ключи — те же, что у хуков экранов: Главная берёт
// ответы из кэша, а не запрашивает второй раз.
import { setSession } from '@sosed/api-client';
import {
  NEW_JOBS_HOURS,
  availableTodayQueryOptions,
  categoriesQueryOptions,
  citiesQueryOptions,
  clientConfigQueryOptions,
  jobsCountQueryOptions,
  myJobsQueryOptions,
} from '@sosed/hooks';
import { createMockPlatform } from '@sosed/platform/mock';
import { createMemoryHistory } from '@tanstack/react-router';
import { waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { ME } from '../testing/fixtures.ts';
import { API_ORIGIN } from '../testing/msw.ts';
import { assemble } from './bootstrap.ts';
import { startLaunch } from './startup.ts';

function launch(path: string, startParam?: string) {
  const { platform } = createMockPlatform({ startParam });
  const app = assemble(platform, {
    version: '0.1.0',
    history: createMemoryHistory({ initialEntries: [path] }),
    baseUrl: API_ORIGIN,
  });
  startLaunch(app);
  return app;
}

afterEach(() => setSession(null));

describe('launch before the first frame', () => {
  it('requests client-config and home dictionaries right away, home data after sign-in', async () => {
    const { queryClient } = launch('/');
    const cached = (queryKey: readonly unknown[]) => queryClient.getQueryData(queryKey);

    // до первого кадра React: StartupGate и Главная найдут их в кэше
    expect(queryClient.isFetching({ queryKey: clientConfigQueryOptions().queryKey })).toBe(1);
    await waitFor(() => {
      expect(cached(clientConfigQueryOptions().queryKey)).toBeDefined();
      expect(cached(citiesQueryOptions('ru').queryKey)).toBeDefined();
      expect(cached(categoriesQueryOptions('ru').queryKey)).toBeDefined();
    });

    // вход решил город (home_city_id) — «Свободны сегодня», «Ищете подработку?» и свои заявки
    const cityId = ME.home_city_id ?? 0;
    await waitFor(() => {
      expect(cached(availableTodayQueryOptions('ru', cityId, null).queryKey)).toBeDefined();
      expect(
        cached(jobsCountQueryOptions({ city_id: cityId }, NEW_JOBS_HOURS).queryKey),
      ).toBeDefined();
      expect(cached(myJobsQueryOptions().queryKey)).toBeDefined();
    });
  });

  it('does not warm home data when the launch opens another screen', async () => {
    const { queryClient, launch: signIn } = launch('/profile');
    await signIn();
    await waitFor(() => expect(queryClient.isFetching()).toBe(0));
    const cityId = ME.home_city_id ?? 0;
    expect(
      queryClient.getQueryData(availableTodayQueryOptions('ru', cityId, null).queryKey),
    ).toBeUndefined();
    expect(queryClient.getQueryData(myJobsQueryOptions().queryKey)).toBeUndefined();
  });
});
