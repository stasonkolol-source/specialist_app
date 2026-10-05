// Портфолио S37, работа и фото профиля S34 (DEVELOPMENT_PLAN 2.11) на фейках backend кабинета и
// media: работы по порядку, загрузка и прикрепление, лимиты, файл без обработки, подпись и место,
// удаление, фото профиля и строка «Портфолио» кабинета; состояния модерации работы (6.7).
import type { WorkOut } from '@sosed/api-client';
import { setSession } from '@sosed/api-client';
import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { pressMainButton, startApp } from '../../testing/app.tsx';
import { FIRST_SERVICE, PORTFOLIO, PROFILE_FILLED } from '../../testing/fixtures.ts';
import { profileHandlers, server } from '../../testing/msw.ts';
import { ProfileBackend } from '../../testing/profileBackend.ts';

// в jsdom нет холста и XHR в хранилище: файл «доходит» в хранилище сразу (тест может задержать)
const transport = vi.hoisted(() => ({
  put: vi.fn(async () => ({ status: 200, etag: '"e"' as string | null })),
}));
vi.mock('./shared/uploads.ts', () => ({ mediaTransport: transport }));

afterEach(() => setSession(null));

const PUBLISHED = { ...PROFILE_FILLED, status: 'published' as const };

function withBackend(works: readonly WorkOut[] = PORTFOLIO.slice(0, 4)): ProfileBackend {
  const backend = new ProfileBackend(PUBLISHED, [FIRST_SERVICE], { works });
  server.use(...profileHandlers(() => backend));
  return backend;
}

const writes = (backend: ProfileBackend) =>
  backend.log.filter((entry) => !entry.request.startsWith('GET'));

const click = (element: HTMLElement) =>
  act(async () => {
    fireEvent.click(element);
  });

const photo = (name: string) => new File(['jpeg'], name, { type: 'image/jpeg' });

/** Выбор файлов в системном диалоге: change у скрытого input[type=file]. */
async function choose(files: File[]) {
  const input = document.querySelector<HTMLInputElement>('input[type="file"]');
  if (!input) throw new Error('нет выбора файлов');
  await act(async () => {
    fireEvent.change(input, { target: { files } });
  });
}

describe('S37 portfolio', () => {
  it('shows the works in order with the count, the limits and a video badge', async () => {
    withBackend();
    const { app } = startApp('/cabinet/portfolio');

    expect(await screen.findByText('4 работы')).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'Портфолио', level: 1 })).toBeTruthy();
    expect(
      screen.getByText(
        'До 60 фото и 6 видео по 60 секунд. Лица клиентов и номера квартир лучше скрыть.',
      ),
    ).toBeTruthy();
    const works = screen.getAllByRole('link').map((link) => link.getAttribute('aria-label'));
    expect(works).toEqual(['Люстра, Лиман', 'Видео: Подсветка кухни', 'Щиток', 'Бра в спальне']);

    await click(screen.getByRole('link', { name: 'Щиток' }));
    await waitFor(() =>
      expect(app.router.state.location.pathname).toBe(`/cabinet/portfolio/${PORTFOLIO[2]?.id}`),
    );
  });

  it('uploads chosen photos and adds them as works at the end', async () => {
    const backend = withBackend(PORTFOLIO.slice(0, 1));
    startApp('/cabinet/portfolio');
    await screen.findByText('1 работа');

    await choose([photo('kitchen.jpg'), photo('hall.jpg')]);

    await waitFor(() => expect(screen.getByText('3 работы')).toBeTruthy());
    const attached = writes(backend).map((entry) => entry.request);
    expect(attached).toEqual(['POST /me/profile/portfolio', 'POST /me/profile/portfolio']);
    expect(backend.works.map((work) => work.media?.status)).toEqual(['ready', 'ready', 'ready']);
    // новая работа ждёт модерации (6.7): бейдж «На проверке»
    expect(screen.getByRole('link', { name: 'Работа 3, На проверке' })).toBeTruthy();
    expect(screen.queryByRole('status')).toBeNull();
  });

  it('does not upload files over the limit and says how many were skipped', async () => {
    const photos = Array.from({ length: 60 }, (_, n) => ({
      ...PORTFOLIO[0],
      id: `work-${n}`,
      position: n,
    })) as WorkOut[];
    const backend = withBackend(photos);
    startApp('/cabinet/portfolio');
    await screen.findByText('60 работ');

    await choose([photo('one-more.jpg')]);

    expect(
      await screen.findByText('1 файл не поместился: в портфолио до 60 фото и 6 видео'),
    ).toBeTruthy();
    expect(writes(backend)).toEqual([]);
  });

  it('keeps a file the server could not process as a tile to remove', async () => {
    const backend = withBackend(PORTFOLIO.slice(0, 1));
    backend.media.outcome = 'rejected';
    startApp('/cabinet/portfolio');
    await screen.findByText('1 работа');

    await choose([photo('blurry.jpg')]);

    const tile = await screen.findByRole('alert');
    expect(within(tile).getByText('Не подходит')).toBeTruthy();
    expect(within(tile).queryByRole('button', { name: 'Повторить' })).toBeNull();
    await click(within(tile).getByRole('button', { name: 'Убрать' }));

    await waitFor(() => expect(screen.queryByRole('alert')).toBeNull());
    expect(backend.works).toHaveLength(1);
    expect([...backend.media.assets.values()].map((media) => media.status)).toEqual(['deleted']);
  });

  it('offers to remove a work whose file failed processing', async () => {
    const [first, second] = PORTFOLIO;
    if (!first?.media || !second) throw new Error('fixture');
    const rejected = { ...first, media: { ...first.media, status: 'rejected' } };
    const backend = withBackend([rejected, { ...second, position: 1 }]);
    startApp('/cabinet/portfolio');

    const tile = await screen.findByRole('alert');
    await click(within(tile).getByRole('button', { name: 'Убрать' }));

    await waitFor(() => expect(screen.getByText('1 работа')).toBeTruthy());
    expect(writes(backend)).toEqual([
      { request: `DELETE /me/profile/portfolio/${first.id}`, body: undefined },
    ]);
  });

  it('marks a work on review and offers to remove one hidden by the moderator', async () => {
    const [first, second, third] = PORTFOLIO;
    if (!first || !second || !third) throw new Error('fixture');
    const backend = withBackend([
      { ...first, status: 'pending' },
      { ...second, position: 1, status: 'rejected' },
      { ...third, position: 2 },
    ]);
    startApp('/cabinet/portfolio');

    const pending = await screen.findByRole('link', { name: 'Люстра, Лиман, На проверке' });
    expect(within(pending).getByText('На проверке')).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Щиток' })).toBeTruthy(); // опубликованная — без бейджа
    expect(screen.getAllByText('На проверке')).toHaveLength(1);
    const hidden = await screen.findByRole('alert');
    expect(within(hidden).getByText('Скрыто модератором')).toBeTruthy();
    await click(within(hidden).getByRole('button', { name: 'Убрать' }));

    await waitFor(() => expect(screen.getByText('2 работы')).toBeTruthy());
    expect(writes(backend)).toEqual([
      { request: `DELETE /me/profile/portfolio/${second.id}`, body: undefined },
    ]);
  });
});

describe('S37 leaving while files upload', () => {
  /** Передача, которая не заканчивается: файл остаётся «Загрузка …». */
  const stall = () => transport.put.mockImplementationOnce(() => new Promise(() => {}));
  const work = () => screen.getByRole('link', { name: 'Люстра, Лиман' });

  it('asks first and stays when the person changes their mind', async () => {
    withBackend(PORTFOLIO.slice(0, 1));
    stall();
    const { app, telegram } = startApp('/cabinet/portfolio', { popupAnswer: null });
    await screen.findByText('1 работа');
    await choose([photo('kitchen.jpg')]);
    expect(await screen.findByRole('status')).toBeTruthy();

    await click(work());

    await waitFor(() =>
      expect(telegram.callsOf('web_app_open_popup').at(-1)?.message).toBe(
        'Файлы ещё загружаются. Уйти и остановить загрузку?',
      ),
    );
    expect(app.router.state.location.pathname).toBe('/cabinet/portfolio');
    expect(screen.getByRole('status')).toBeTruthy();
  });

  it('leaves once the person agrees', async () => {
    withBackend(PORTFOLIO.slice(0, 1));
    stall();
    const { app } = startApp('/cabinet/portfolio', { popupAnswer: 'ok' });
    await screen.findByText('1 работа');
    await choose([photo('kitchen.jpg')]);
    await screen.findByRole('status');

    await click(work());

    await waitFor(() =>
      expect(app.router.state.location.pathname).toBe(`/cabinet/portfolio/${PORTFOLIO[0]?.id}`),
    );
  });
});

describe('S37 work', () => {
  const caption = () => screen.findByRole<HTMLInputElement>('textbox', { name: 'Подпись' });

  it('saves a new caption and an earlier place in one go', async () => {
    const backend = withBackend();
    const { app, telegram } = startApp(`/cabinet/portfolio/${PORTFOLIO[2]?.id}`);

    expect((await caption()).value).toBe('Щиток');
    expect(screen.getByText('3 из 4')).toBeTruthy();
    fireEvent.change(await caption(), { target: { value: '  Щиток   в Лимане ' } });
    await click(screen.getByRole('button', { name: 'Раньше' }));
    await click(screen.getByRole('button', { name: 'Раньше' }));
    expect(screen.getByText('1 из 4')).toBeTruthy();
    expect(screen.getByRole<HTMLButtonElement>('button', { name: 'Раньше' }).disabled).toBe(true);
    await pressMainButton(telegram);

    await waitFor(() => expect(writes(backend)).toHaveLength(2));
    const ids = PORTFOLIO.slice(0, 4).map((work) => work.id);
    expect(writes(backend)).toEqual([
      {
        request: `PATCH /me/profile/portfolio/${ids[2]}`,
        body: { caption: 'Щиток в Лимане' },
      },
      {
        request: 'PUT /me/profile/portfolio/order',
        body: { item_ids: [ids[2], ids[0], ids[1], ids[3]] },
      },
    ]);
    await waitFor(() => expect(app.router.state.location.pathname).toBe('/cabinet/portfolio'));
    const order = screen.getAllByRole('link').map((link) => link.getAttribute('aria-label'));
    expect(order[0]).toBe('Щиток в Лимане');
  });

  it('saves nothing when nothing changed', async () => {
    const backend = withBackend();
    const { app, telegram } = startApp(`/cabinet/portfolio/${PORTFOLIO[0]?.id}`);

    await caption();
    await pressMainButton(telegram);

    await waitFor(() => expect(app.router.state.location.pathname).toBe('/cabinet/portfolio'));
    expect(writes(backend)).toEqual([]);
  });

  it('removes a work after confirmation', async () => {
    const backend = withBackend();
    const { app } = startApp(`/cabinet/portfolio/${PORTFOLIO[0]?.id}`, { popupAnswer: 'ok' });

    await caption();
    await click(screen.getByRole('button', { name: 'Убрать из портфолио' }));

    await waitFor(() => expect(app.router.state.location.pathname).toBe('/cabinet/portfolio'));
    expect(writes(backend)).toEqual([
      { request: `DELETE /me/profile/portfolio/${PORTFOLIO[0]?.id}`, body: undefined },
    ]);
    expect(backend.works.map((work) => work.position)).toEqual([0, 1, 2]);
  });
});

describe('S34 profile photo', () => {
  it('uploads a new photo, sets it at once and shows it from the server', async () => {
    const backend = withBackend();
    startApp('/cabinet/profile');

    const section = await screen.findByRole('region', { name: 'Фото профиля' });
    expect(within(section).getByText('Без фото клиенты видят инициалы')).toBeTruthy();
    await choose([photo('me.jpg')]);

    await waitFor(() =>
      expect(within(section).getByRole('img').getAttribute('src')).toMatch(/\/thumb\.webp$/),
    );
    expect(within(section).getByText('Ваше фото')).toBeTruthy();
    const [avatar] = writes(backend);
    expect(avatar?.request).toBe('PUT /me/profile/avatar');
    expect(backend.profile?.avatar?.status).toBe('ready');
  });
});

describe('S33 portfolio row', () => {
  it('shows how many works there are and opens S37', async () => {
    withBackend();
    const { app } = startApp('/cabinet');

    const row = await screen.findByRole('link', { name: /Портфолио/ });
    await waitFor(() => expect(row.textContent).toContain('4'));
    // 4 работы — портфолио засчитано; первым делом — фото профиля
    expect(screen.getByText('Добавьте фото профиля')).toBeTruthy();

    await click(row);
    await waitFor(() => expect(app.router.state.location.pathname).toBe('/cabinet/portfolio'));
  });
});
