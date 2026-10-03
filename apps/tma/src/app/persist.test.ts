// Публичные справочники между запусками (app/persist.ts): конфиг и города поднимаются до первого
// кадра со временем их ответа; чужая версия, старые записи и личное — нет; без хранилища — без них.
import type { ClientConfigOut } from '@sosed/api-client';
import { getIdentityGetMeQueryKey } from '@sosed/api-client';
import { citiesQueryKey, clientConfigQueryOptions } from '@sosed/hooks';
import { QueryClient } from '@tanstack/react-query';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { CLIENT_CONFIG, ME } from '../testing/fixtures.ts';
import { persistPublicQueries, restorePublicQueries } from './persist.ts';

const CONFIG_KEY = clientConfigQueryOptions().queryKey;
const CITIES = [{ id: 1, slug: 'novi-sad', name: 'Нови-Сад', status: 'active' }];

/** Первый запуск: ответы пришли и сохранились. */
function firstLaunch(version = '0.1.0', at = Date.now()) {
  const client = new QueryClient();
  const stop = persistPublicQueries(client, version);
  client.setQueryData(CONFIG_KEY, CLIENT_CONFIG, { updatedAt: at });
  client.setQueryData(citiesQueryKey('ru'), CITIES, { updatedAt: at });
  client.setQueryData(getIdentityGetMeQueryKey(), ME, { updatedAt: at });
  stop();
}

afterEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});

describe('public queries between launches', () => {
  it('restores config and cities with their response time, nothing personal', () => {
    const at = Date.now() - 10 * 60_000;
    firstLaunch('0.1.0', at);

    const client = new QueryClient();
    restorePublicQueries(client, '0.1.0');

    expect(client.getQueryData<ClientConfigOut>(CONFIG_KEY)).toEqual(CLIENT_CONFIG);
    expect(client.getQueryState(CONFIG_KEY)?.dataUpdatedAt).toBe(at);
    expect(client.getQueryData(citiesQueryKey('ru'))).toEqual(CITIES);
    expect(client.getQueryData(getIdentityGetMeQueryKey())).toBeUndefined();
    expect(localStorage.getItem('sosed:public-queries')).not.toContain(ME.display_name);
  });

  it('does not keep a config with maintenance on: the next launch would start with S49', () => {
    const client = new QueryClient();
    const stop = persistPublicQueries(client, '0.1.0');
    const maintenance = {
      ...CLIENT_CONFIG,
      flags: { ...CLIENT_CONFIG.flags, 'platform.maintenance': true },
    };
    client.setQueryData(CONFIG_KEY, maintenance);
    stop();

    const next = new QueryClient();
    restorePublicQueries(next, '0.1.0');
    expect(next.getQueryData(CONFIG_KEY)).toBeUndefined();
  });

  it('ignores another app version and records older than a day', () => {
    firstLaunch('0.1.0');
    const other = new QueryClient();
    restorePublicQueries(other, '0.2.0');
    expect(other.getQueryData(CONFIG_KEY)).toBeUndefined();

    firstLaunch('0.1.0');
    const later = new QueryClient();
    restorePublicQueries(later, '0.1.0', Date.now() + 25 * 60 * 60_000);
    expect(later.getQueryData(CONFIG_KEY)).toBeUndefined();
  });

  it('works without storage', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new DOMException('denied', 'SecurityError');
    });
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('full', 'QuotaExceededError');
    });
    const client = new QueryClient();
    expect(() => restorePublicQueries(client, '0.1.0')).not.toThrow();
    expect(() => firstLaunch()).not.toThrow();
  });
});
