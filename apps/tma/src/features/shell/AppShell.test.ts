// Вкладка «Заявки» узнаёт о своих заявках клиента из кэша по ключу, записанному в AppShell: модуль
// запросов заявок первому экрану не нужен. Ключ должен совпадать с тем, что заполняют экраны.
import { getJobsListMyJobsQueryKey } from '@sosed/api-client';
import { describe, expect, it } from 'vitest';

import { MY_JOBS_KEY } from './AppShell.tsx';

describe('AppShell', () => {
  it('reads own jobs from the cache entry the screens fill', () => {
    expect(MY_JOBS_KEY).toEqual(getJobsListMyJobsQueryKey());
  });
});
