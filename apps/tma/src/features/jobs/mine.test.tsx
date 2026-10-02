// Свои заявки клиента S22 и S23 (DEVELOPMENT_PLAN 5.6) на фейке backend: «Мои заявки» разделами с
// «3 отклика — выберите исполнителя» и «2 новых», чипы; своя заявка — статус, район, бюджет,
// просмотры, места, отклики карточками («Откликнулся первым», «Подработка», рейтинг), закрыть с
// причиной, пригласить специалиста; ссылка на свою заявку ведёт владельца на S23; вкладка
// «Заявки» клиенту открывает «Мои заявки»; на Главной — «Мои активные заявки». «Изменить» —
// мастер с полями заявки и сохранение с If-Match; чужая правка между ними — «откройте заново».
import { setSession } from '@sosed/api-client';
import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { mainButton, pressMainButton, startApp } from '../../testing/app.tsx';
import { E2E_NOW } from '../../testing/fixtures.ts';
import { JobsBackend, myJobsFixture } from '../../testing/jobsBackend.ts';
import { jobsHandlers, server } from '../../testing/msw.ts';
import { useDraftStore } from './shared/draft.ts';

const [CHANDELIER] = myJobsFixture();
const MANAGE = `/jobs/${CHANDELIER?.id ?? ''}/manage`;

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'], now: new Date(E2E_NOW) });
});
afterEach(() => {
  vi.useRealTimers();
  setSession(null);
});

function withMine(): JobsBackend {
  const backend = new JobsBackend().seedMine();
  server.use(...jobsHandlers(() => backend));
  return backend;
}

const click = (element: HTMLElement) =>
  act(async () => {
    fireEvent.click(element);
  });

describe('S22 my jobs', () => {
  it('groups jobs and shows responses waiting for a choice', async () => {
    withMine();
    const { app } = startApp('/jobs/mine');

    expect(await screen.findByRole('heading', { name: 'Активные', level: 2 })).toBeTruthy();
    const chandelier = screen.getByRole('link', { name: /Повесить люстру/ });
    expect(within(chandelier).getByText('3 отклика — выберите исполнителя')).toBeTruthy();
    expect(within(chandelier).getByText('2 новых')).toBeTruthy();
    const cleaning = screen.getByRole('link', { name: /Генеральная уборка/ });
    expect(within(cleaning).getByText('Ждём откликов')).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'Архив', level: 2 })).toBeTruthy();
    const done = screen.getByRole('link', { name: /Уборка после ремонта/ });
    expect(within(done).getByText('Закрыта')).toBeTruthy();

    const chips = screen.getByRole('group', { name: 'Статус заявок' });
    await click(within(chips).getByRole('button', { name: 'Архив' }));
    expect(screen.queryByRole('link', { name: /Повесить люстру/ })).toBeNull();
    await click(within(chips).getByRole('button', { name: 'Все' }));

    await click(screen.getByRole('link', { name: /Повесить люстру/ }));
    await waitFor(() => expect(app.router.state.location.pathname).toBe(MANAGE));
  });

  it('opens for a client from the jobs tab', async () => {
    withMine();
    const { app } = startApp('/');
    const tabs = await screen.findByRole('navigation', { name: 'Разделы' });

    await click(within(tabs).getByRole('link', { name: 'Заявки' }));

    await waitFor(() => expect(app.router.state.location.pathname).toBe('/jobs/mine'));
  });
});

describe('S23 manage job', () => {
  it('shows the job, its views, slots and response cards', async () => {
    withMine();
    startApp(MANAGE);

    expect(await screen.findByRole('heading', { name: 'Повесить люстру', level: 1 })).toBeTruthy();
    expect(screen.getByText('Приём откликов')).toBeTruthy();
    expect(await screen.findByText('Лиман · точный адрес откроется выбранному')).toBeTruthy();
    expect(screen.getByText(/^5\s000\sRSD · фикс, за работу$/u)).toBeTruthy();
    expect(screen.getByText('12 просмотров')).toBeTruthy();
    expect(screen.getByText('3 из 5')).toBeTruthy();
    const first = await screen.findByRole('article', { name: /^Алексей Морозов/ });
    expect(within(first).getByText('4,9 · 37 отзывов · Лиман')).toBeTruthy();
    expect(within(first).getByText('Откликнулся первым')).toBeTruthy();
    expect(within(first).getByText('Телефон подтверждён')).toBeTruthy();
    expect(within(first).getByText('Новый')).toBeTruthy();
    const casual = screen.getByRole('article', { name: /^Иван Гаврилов/ });
    expect(within(casual).getByText('Отзывов пока нет')).toBeTruthy();
    expect(within(casual).getByText('Подработка')).toBeTruthy();
    expect(
      screen.getByText('Выберите исполнителя — только ему откроется точный адрес.'),
    ).toBeTruthy();
  });

  it('closes the job with a reason', async () => {
    const backend = withMine();
    startApp(MANAGE);
    await screen.findByRole('heading', { name: 'Повесить люстру', level: 1 });

    await click(screen.getByRole('button', { name: /Закрыть заявку/ }));
    const sheet = screen.getByRole('dialog', { name: 'Почему закрываете заявку?' });
    await click(within(sheet).getByRole('button', { name: 'Нашёл в другом месте' }));

    await waitFor(() =>
      expect(backend.actions).toEqual([
        { jobId: CHANDELIER?.id, action: 'close', reason: 'hired_elsewhere' },
      ]),
    );
    expect(await screen.findByText('Закрыта')).toBeTruthy();
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('invites a specialist from the catalog', async () => {
    const backend = withMine();
    startApp(MANAGE);
    await screen.findByRole('heading', { name: 'Повесить люстру', level: 1 });

    await click(screen.getByRole('button', { name: 'Пригласить' }));
    const sheet = screen.getByRole('dialog', { name: 'Пригласите специалистов' });
    const [invite] = await within(sheet).findAllByRole('button', { name: 'Пригласить' });
    if (!invite) throw new Error('no specialists to invite');
    await click(invite);

    await waitFor(() => expect(backend.invites.get(CHANDELIER?.id ?? '')).toHaveLength(1));
    expect(await within(sheet).findByText('Приглашён')).toBeTruthy();
  });

  it('is where the owner lands from a link to the job', async () => {
    withMine();
    const { app } = startApp(`/jobs/${CHANDELIER?.id ?? ''}`);

    await waitFor(() => expect(app.router.state.location.pathname).toBe(MANAGE));
    expect(await screen.findByRole('heading', { name: 'Повесить люстру', level: 1 })).toBeTruthy();
  });
});

describe('S03 my active jobs', () => {
  it('lists open jobs with their responses and leads to them', async () => {
    withMine();
    const { app } = startApp('/');

    const block = await screen.findByRole('region', { name: 'Мои активные заявки' });
    const row = within(block).getByRole('link', { name: /Повесить люстру/ });
    expect(within(row).getByText('3 отклика · 2 новых')).toBeTruthy();
    expect(within(block).getByText('Ждём откликов')).toBeTruthy();
    expect(within(block).queryByText('Уборка после ремонта')).toBeNull();

    await click(row);
    await waitFor(() => expect(app.router.state.location.pathname).toBe(MANAGE));
  });
});

describe('S23 edit', () => {
  /** «Изменить» и шаги мастера до «Проверьте заявку». */
  async function toPreview(telegram: Parameters<typeof pressMainButton>[0]) {
    await screen.findByRole('heading', { name: 'Повесить люстру', level: 1 });
    await click(screen.getByRole('button', { name: 'Изменить' }));
    expect(await screen.findByText('Шаг 1 из 4 · правка заявки')).toBeTruthy();
    expect(screen.getByDisplayValue('Повесить люстру')).toBeTruthy();
    for (const step of ['Шаг 2 из 4 · правка заявки', 'Шаг 3 из 4 · правка заявки']) {
      await pressMainButton(telegram);
      expect(await screen.findByText(step)).toBeTruthy();
    }
    await pressMainButton(telegram);
    await waitFor(() => expect(mainButton(telegram)?.text).toBe('Сохранить изменения'));
  }

  it('saves the job with the version it was opened at', async () => {
    const backend = withMine();
    const { app, telegram } = startApp(MANAGE);

    await toPreview(telegram);
    await pressMainButton(telegram);

    await waitFor(() => expect(app.router.state.location.pathname).toBe(MANAGE));
    const [update] = backend.updates;
    expect(update?.ifMatch).toBe('"1"');
    expect(update?.body.title).toBe('Повесить люстру');
    expect(update?.body.urgency).toBe('today');
    expect(backend.jobs.get(CHANDELIER?.id ?? '')?.version).toBe(2);
    // правка закрыта: следующая начнётся с той версии, что видна на S23
    await waitFor(() => expect(useDraftStore.getState().editing).toBeNull());
  });

  it('asks to reopen the job changed elsewhere', async () => {
    const backend = withMine();
    const { app, telegram } = startApp(MANAGE);
    await toPreview(telegram);
    const id = CHANDELIER?.id ?? '';
    const job = backend.jobs.get(id);
    if (job) backend.jobs.set(id, { ...job, version: job.version + 1 });

    await pressMainButton(telegram);

    expect(
      await screen.findByText(
        'Заявку уже изменили в другом месте — откройте её заново и повторите правку.',
      ),
    ).toBeTruthy();
    await click(screen.getByRole('button', { name: 'Открыть заявку' }));
    await waitFor(() => expect(app.router.state.location.pathname).toBe(MANAGE));
  });
});
