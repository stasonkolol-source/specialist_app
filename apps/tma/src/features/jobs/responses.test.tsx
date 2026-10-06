// Отклики S15–S17 и шаблоны S57 (DEVELOPMENT_PLAN 5.5) на фейке backend: MainButton S15 по местам и
// своему отклику; форма S16 с основным шаблоном, проверкой полей, ключом идемпотентности, ошибкой
// сервера, «Сохранить как шаблон» и правкой своего отклика; «Мои отклики» S17 — чипы с числами,
// квота дня, карточки по состояниям, «Отозвать»; шаблоны S57 — основной, «Сделать основным»,
// третий — «удалите один», удаление и новый шаблон.
import { setSession } from '@sosed/api-client';
import { uuidToBase62 } from '@sosed/links';
import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { HttpResponse, http } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { mainButton, pressBackButton, pressMainButton, startApp } from '../../testing/app.tsx';
import { problem } from '../../testing/backend.ts';
import { E2E_NOW } from '../../testing/fixtures.ts';
import type { FeedFixture } from '../../testing/jobsBackend.ts';
import {
  FEED_JOBS,
  JobsBackend,
  dealCardFixture,
  myJobsFixture,
  myResponsesFixture,
  responseCardsFixture,
  templatesFixture,
} from '../../testing/jobsBackend.ts';
import { jobsHandlers, server } from '../../testing/msw.ts';
import { respondInTelegramLink } from './s15-job/telegram.ts';

const job = (title: string) => {
  const found = FEED_JOBS.find((item) => item.card.title === title);
  if (!found) throw new Error(title);
  return found;
};
const WARDROBE: FeedFixture = job('Собрать шкаф PAX, 2 м');
const MOVING: FeedFixture = job('Помочь с переездом: 1-комн., 3 этаж без лифта');
const NAILS: FeedFixture = job('Маникюр с покрытием на дому');

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'], now: new Date(E2E_NOW) });
});
afterEach(() => {
  vi.useRealTimers();
  setSession(null);
});

function withJobs(setup: (backend: JobsBackend) => void = () => undefined): JobsBackend {
  const backend = new JobsBackend();
  setup(backend);
  server.use(...jobsHandlers(() => backend));
  return backend;
}

const click = (element: HTMLElement) =>
  act(async () => {
    fireEvent.click(element);
  });

const type = (element: HTMLElement, value: string) =>
  act(async () => {
    fireEvent.change(element, { target: { value } });
  });

describe('S15 respond button', () => {
  it('opens the form while there are places', async () => {
    withJobs();
    const { app, telegram } = startApp(`/jobs/${MOVING.card.id}`);

    await waitFor(() => expect(mainButton(telegram)?.text).toBe('Откликнуться · осталось 3 места'));
    expect(mainButton(telegram)?.is_active).toBe(true);
    await pressMainButton(telegram);

    await waitFor(() =>
      expect(app.router.state.location.pathname).toBe(`/jobs/${MOVING.card.id}/respond`),
    );
  });

  it('says there are no places on a full job', async () => {
    withJobs();
    const { telegram } = startApp(`/jobs/${NAILS.card.id}`);

    await waitFor(() => expect(mainButton(telegram)?.text).toBe('Мест нет'));
    expect(mainButton(telegram)?.is_active).toBe(false);
  });

  it('leads to my responses after responding', async () => {
    withJobs((backend) => {
      backend.responses = myResponsesFixture();
    });
    const { app, telegram } = startApp(`/jobs/${WARDROBE.card.id}`);

    await waitFor(() => expect(mainButton(telegram)?.text).toBe('Вы откликнулись'));
    await pressMainButton(telegram);

    await waitFor(() => expect(app.router.state.location.pathname).toBe('/jobs/responses'));
  });

  it('leads straight to fixing a response hidden by moderation (MU-10)', async () => {
    withJobs((backend) => {
      backend.responses = myResponsesFixture().map((response) =>
        response.job.id === WARDROBE.card.id ? { ...response, review: 'blocked' } : response,
      );
    });
    const { app, telegram } = startApp(`/jobs/${WARDROBE.card.id}`);

    await waitFor(() => expect(mainButton(telegram)?.text).toBe('Исправить отклик'));
    await pressMainButton(telegram);

    await waitFor(() =>
      expect(app.router.state.location.pathname).toBe(`/jobs/${WARDROBE.card.id}/respond`),
    );
  });
});

describe('S16 respond', () => {
  it('starts from the primary template and sends it with a key', async () => {
    const backend = withJobs((it) => {
      it.templates = templatesFixture();
    });
    const { app, telegram } = startApp(`/jobs/${MOVING.card.id}/respond`);

    expect(await screen.findByText('Отклик на заявку')).toBeTruthy();
    expect(screen.getByRole('heading', { level: 1 }).textContent).toBe(MOVING.card.title);
    const message = screen.getByRole('textbox', { name: 'Сообщение клиенту' });
    expect((message as HTMLTextAreaElement).value).toMatch(/^Здравствуйте! Могу сегодня вечером/);
    expect(screen.getByRole('radio', { name: 'От' }).getAttribute('aria-checked')).toBe('true');
    const templates = screen.getByRole('group', { name: 'Вставить шаблон' });
    expect(
      within(templates)
        .getAllByRole('button')
        .map((chip) => chip.textContent),
    ).toEqual(['Могу сегодня', 'Свой инструмент']);
    // шаблонов уже два — сохранять некуда
    const save = screen.getByRole('checkbox', { name: 'Сохранить как шаблон' });
    expect((save as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(/Шаблонов уже 2/)).toBeTruthy();
    await waitFor(() => expect(mainButton(telegram)?.text).toBe('Отправить отклик'));

    await pressMainButton(telegram);

    await waitFor(() => expect(app.router.state.location.pathname).toBe('/jobs/responses'));
    expect(app.router.state.location.search).toEqual({ sent: true });
    const [post] = backend.responsePosts;
    expect(post?.key).toBeTruthy();
    expect(post?.body).toEqual({
      message: 'Здравствуйте! Могу сегодня вечером, приеду со своим инструментом.',
      price_type: 'from',
      price_amount: 200_000,
      availability_note: 'сегодня',
      template_id: '0199dd20-0000-7000-8000-000000000001',
    });
    expect(
      await screen.findByText('Отклик отправлен — клиент увидит его после проверки'),
    ).toBeTruthy();
    const card = await screen.findByRole('article', { name: /Помочь с переездом/ });
    expect(within(card).getByText('На проверке')).toBeTruthy();
    expect(within(card).getByText('Ждёт решения клиента')).toBeTruthy();
  });

  it('checks the fields, then sends a changed offer and saves it as a template', async () => {
    const backend = withJobs();
    const { telegram } = startApp(`/jobs/${MOVING.card.id}/respond`);
    const message = await screen.findByRole('textbox', { name: 'Сообщение клиенту' });
    await waitFor(() => expect(mainButton(telegram)?.text).toBe('Отправить отклик'));

    await pressMainButton(telegram);

    expect(screen.getByText('Напишите сообщение клиенту')).toBeTruthy();
    expect(screen.getByText('Укажите цену')).toBeTruthy();
    expect(backend.responsePosts).toHaveLength(0);

    await type(message, 'Добрый день! Перевезу аккуратно, есть помощник.');
    await type(screen.getByRole('textbox', { name: 'Цена, RSD' }), '12000');
    expect((screen.getByRole('textbox', { name: 'Цена, RSD' }) as HTMLInputElement).value).toMatch(
      /^12\s000$/u,
    );
    await type(screen.getByRole('textbox', { name: 'Когда смогу' }), 'В субботу утром');
    await click(screen.getByRole('checkbox', { name: 'Сохранить как шаблон' }));
    await pressMainButton(telegram);

    await waitFor(() => expect(backend.templates).toHaveLength(1));
    expect(backend.responsePosts.at(-1)?.body).toEqual({
      message: 'Добрый день! Перевезу аккуратно, есть помощник.',
      price_type: 'fixed',
      price_amount: 1_200_000,
      availability_note: 'В субботу утром',
      template_id: null,
    });
    // название — первая фраза после приветствия
    expect(backend.templates[0]?.title).toBe('Перевезу аккуратно, есть помощник');
  });

  // ADV-10: поле выбрасывало всё, кроме цифр, — «1.500,00» становилось 150 000 RSD
  it('reads a pasted price with kopecks as whole dinars, not ×100', async () => {
    const backend = withJobs();
    const { telegram } = startApp(`/jobs/${MOVING.card.id}/respond`);
    const message = await screen.findByRole('textbox', { name: 'Сообщение клиенту' });
    await type(message, 'Добрый день! Перевезу аккуратно, есть помощник.');
    const price = screen.getByRole<HTMLInputElement>('textbox', { name: 'Цена, RSD' });
    await type(price, '1.500,00');
    expect(price.value).toMatch(/^1\s500,$/u);
    await type(price, '1500.00');
    expect(price.value).toMatch(/^1\s500,$/u);
    await pressMainButton(telegram);

    await waitFor(() => expect(backend.responsePosts).toHaveLength(1));
    expect(backend.responsePosts[0]?.body).toMatchObject({ price_amount: 150_000 });
  });

  // UXM-10: «Назад» молча стирал набранный отклик
  it('asks before Back discards a typed offer and keeps it when the person stays', async () => {
    withJobs();
    const path = `/jobs/${MOVING.card.id}/respond`;
    const { app, telegram } = startApp(path, { popupAnswer: null });
    const message = await screen.findByRole('textbox', { name: 'Сообщение клиенту' });
    await type(message, 'Добрый день! Перевезу аккуратно.');

    await pressBackButton(telegram);

    await waitFor(() =>
      expect(telegram.callsOf('web_app_open_popup').at(-1)?.message).toMatch(
        /^Уйти\sс\sэкрана\?\sНабранный\sотклик\sне\sсохранится\.$/u,
      ),
    );
    expect(app.router.state.location.pathname).toBe(path);
    expect(
      (screen.getByRole('textbox', { name: 'Сообщение клиенту' }) as HTMLTextAreaElement).value,
    ).toBe('Добрый день! Перевезу аккуратно.');
  });

  it('leaves an untouched form without asking', async () => {
    withJobs();
    const { app, telegram } = startApp(`/jobs/${MOVING.card.id}/respond`, { popupAnswer: null });
    await screen.findByRole('textbox', { name: 'Сообщение клиенту' });

    await pressBackButton(telegram);

    await waitFor(() => expect(app.router.state.location.pathname).toBe(`/jobs/${MOVING.card.id}`));
    expect(telegram.callsOf('web_app_open_popup')).toHaveLength(0);
  });

  it('shows the server text when the job is already full', async () => {
    const backend = withJobs((it) => {
      it.templates = templatesFixture();
      it.failNextRespond = problem(409, 'job_full', {
        limit: 5,
        detail: 'Свободных мест на заявке больше нет: не больше 5 откликов.',
      });
    });
    const { app, telegram } = startApp(`/jobs/${MOVING.card.id}/respond`);
    await screen.findByText('Отклик на заявку');
    await waitFor(() => expect(mainButton(telegram)?.text).toBe('Отправить отклик'));

    await pressMainButton(telegram);

    expect(
      await screen.findByText('Свободных мест на заявке больше нет: не больше 5 откликов.'),
    ).toBeTruthy();
    expect(app.router.state.location.pathname).toBe(`/jobs/${MOVING.card.id}/respond`);
    expect(backend.responses).toHaveLength(0);
  });

  it('edits my active response in place', async () => {
    const backend = withJobs((it) => {
      it.responses = myResponsesFixture();
    });
    const { telegram } = startApp(`/jobs/${WARDROBE.card.id}/respond`);

    expect(await screen.findByText('Правка отклика')).toBeTruthy();
    const message = screen.getByRole('textbox', { name: 'Сообщение клиенту' });
    expect((message as HTMLTextAreaElement).value).toBe(
      'Соберу шкаф за пару часов, есть опыт с PAX.',
    );
    expect(screen.queryByRole('checkbox', { name: 'Сохранить как шаблон' })).toBeNull();
    await waitFor(() => expect(mainButton(telegram)?.text).toBe('Сохранить изменения'));
    await click(screen.getByRole('radio', { name: 'Договорная' }));

    await pressMainButton(telegram);

    await waitFor(() =>
      expect(backend.responses.find((item) => item.job.id === WARDROBE.card.id)?.price).toEqual({
        type: 'negotiable',
        amount: null,
      }),
    );
    expect(backend.responsePosts).toHaveLength(0);
  });

  it('previews what the client sees', async () => {
    withJobs((it) => {
      it.templates = templatesFixture();
    });
    startApp(`/jobs/${MOVING.card.id}/respond`);
    await screen.findByText('Отклик на заявку');

    await click(screen.getByRole('button', { name: 'Предпросмотр' }));

    const dialog = screen.getByRole('dialog', { name: 'Так отклик увидит клиент' });
    expect(within(dialog).getByText(/Могу сегодня вечером/)).toBeTruthy();
    expect(within(dialog).getByText(/^от 2\s000\sRSD$/u)).toBeTruthy();
    expect(within(dialog).getByText('сегодня')).toBeTruthy();
  });
});

describe('S15 in the browser', () => {
  it('responds in Telegram: the link opens this very job in the Mini App', () => {
    expect(respondInTelegramLink(MOVING.card.id, 'sosed_bot')).toBe(
      `https://t.me/sosed_bot?startapp=j_${uuidToBase62(MOVING.card.id)}`,
    );
    // без бота сборки ссылки нет — остаётся обычная кнопка
    expect(respondInTelegramLink(MOVING.card.id, null)).toBeNull();
  });
});

describe('S17 my responses', () => {
  it('shows chips with counts, the daily quota and cards by state', async () => {
    withJobs((it) => {
      it.responses = myResponsesFixture();
      it.respondedToday = 3;
    });
    startApp('/jobs/responses');

    const chips = await screen.findByRole('group', { name: 'Статус отклика' });
    expect(
      within(chips)
        .getAllByRole('button')
        .map((chip) => chip.textContent),
    ).toEqual(['Все 3', 'Активные 1', 'Выбран 1', 'Не выбран 1', 'Архив']);
    expect(screen.getByText('Сегодня откликов: 3 из 10 — лимит по уровню доверия')).toBeTruthy();
    const chosen = screen.getByRole('article', { name: /Повесить люстру.*Вас выбрали/ });
    expect(within(chosen).getByText('Вас выбрали.')).toBeTruthy();
    expect(within(chosen).getByText('Адрес и время — в сделке')).toBeTruthy();
    expect(within(chosen).getByText(/^3\s500\sRSD$/u)).toBeTruthy();
    const waiting = screen.getByRole('article', { name: /Собрать шкаф/ });
    expect(within(waiting).getByText('Ждёт решения клиента')).toBeTruthy();
    expect(within(waiting).getByText('Первый отклик')).toBeTruthy();
    expect(within(waiting).getByText('откликов 1 из 5')).toBeTruthy();
    const other = screen.getByRole('article', { name: /Течёт смеситель/ });
    expect(within(other).getByText('Клиент выбрал другого')).toBeTruthy();
    expect(within(other).queryByRole('button')).toBeNull();
  });

  it('says the job was closed, not that another performer was chosen', async () => {
    withJobs((it) => {
      it.responses = myResponsesFixture().map((item) =>
        item.status === 'not_selected' ? { ...item, job: { ...item.job, status: 'closed' } } : item,
      );
    });
    startApp('/jobs/responses');

    const closed = await screen.findByRole('article', { name: /Течёт смеситель/ });
    expect(within(closed).getByText('Заявка закрыта')).toBeTruthy();
    expect(within(closed).queryByText('Клиент выбрал другого')).toBeNull();
  });

  it('leads the chosen performer to the deal: «Открыть сделку» is the main button', async () => {
    const [accepted] = myResponsesFixture();
    const [chandelier] = myJobsFixture();
    const [card] = responseCardsFixture();
    if (!accepted || !chandelier || !card) throw new Error('fixtures');
    const deal = { ...dealCardFixture(chandelier, card, 'performer'), response_id: accepted.id };
    const backend = withJobs((it) => {
      it.responses = myResponsesFixture();
      it.dealRole = 'performer';
      it.deals.set(deal.id, deal);
    });
    // сделки отвечают, только когда тест отпустит
    let release: (() => void) | undefined;
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });
    server.use(
      http.get('*/api/v1/me/deals', async ({ request }) => {
        await held;
        const reply = backend.handle('GET', new URL(request.url), null, null, true);
        return HttpResponse.json(reply?.body as Record<string, unknown>, {
          status: reply?.status,
        });
      }),
    );
    const { app } = startApp('/jobs/responses');
    const chosen = await screen.findByRole('article', { name: /Повесить люстру.*Вас выбрали/ });

    // сделки ещё грузятся: главная кнопка уже на месте и ждёт, «Открыть заявку» — вторая
    const toDeal = within(chosen).getByRole('button', { name: 'Открыть сделку' });
    expect(toDeal).toHaveProperty('disabled', true);
    expect(toDeal.getAttribute('aria-busy')).toBe('true');
    expect(within(chosen).getByRole('button', { name: 'Открыть заявку' }).className).toContain(
      'border-line',
    );

    release?.();
    await waitFor(() => expect(toDeal).toHaveProperty('disabled', false));
    expect(toDeal.getAttribute('aria-busy')).toBe('false');
    await click(toDeal);
    await waitFor(() => expect(app.router.state.location.pathname).toBe(`/deals/${deal.id}`));
  });

  it('makes «Открыть заявку» the main button when no deal is found', async () => {
    withJobs((it) => {
      it.responses = myResponsesFixture();
    });
    startApp('/jobs/responses');
    const chosen = await screen.findByRole('article', { name: /Повесить люстру.*Вас выбрали/ });

    await waitFor(() =>
      expect(within(chosen).queryByRole('button', { name: 'Открыть сделку' })).toBeNull(),
    );
    expect(within(chosen).getByRole('button', { name: 'Открыть заявку' }).className).toContain(
      'bg-accent',
    );
  });

  it('filters by chip and withdraws after confirmation', async () => {
    const backend = withJobs((it) => {
      it.responses = myResponsesFixture();
    });
    const { app } = startApp('/jobs/responses', { popupAnswer: 'ok' });
    const chips = await screen.findByRole('group', { name: 'Статус отклика' });

    await click(within(chips).getByRole('button', { name: 'Активные 1' }));

    await waitFor(() => expect(app.router.state.location.search).toEqual({ status: 'active' }));
    await waitFor(() =>
      expect(screen.queryByRole('article', { name: /Повесить люстру/ })).toBeNull(),
    );
    const waiting = screen.getByRole('article', { name: /Собрать шкаф/ });

    await click(within(waiting).getByRole('button', { name: 'Отозвать отклик' }));

    await waitFor(() =>
      expect(backend.responses.find((item) => item.job.id === WARDROBE.card.id)?.status).toBe(
        'withdrawn',
      ),
    );
    expect(await screen.findByText('Здесь пока пусто')).toBeTruthy();
  });

  it('invites to the feed when there are no responses', async () => {
    withJobs();
    startApp('/jobs/responses');

    expect(await screen.findByRole('heading', { name: 'Откликов пока нет' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'К ленте заявок' })).toBeTruthy();
  });
});

/** Названия шаблонов S57 по порядку карточек. */
const cardTitles = () =>
  screen.getAllByRole('article').map((card) => card.querySelector('[id]')?.textContent);

describe('S57 templates', () => {
  it.each([false, true])(
    'retries after a lost create response, changing the key only for an edited form (edited: %s)',
    async (edited) => {
      const backend = withJobs();
      const attempts: { key: string | null; body: string }[] = [];
      server.use(
        http.post('*/api/v1/me/response-templates', async ({ request }) => {
          const key = request.headers.get('Idempotency-Key');
          const body = await request.text();
          const previous = attempts.find((attempt) => attempt.key === key);
          attempts.push({ key, body });
          // Сервер сохраняет успешный ответ; тот же ключ с другим телом даёт 422.
          if (previous && previous.body !== body) {
            return HttpResponse.json(
              problem(422, 'idempotency_key_reused').body as Record<string, unknown>,
              { status: 422 },
            );
          }
          const reply = backend.templated('POST', '/me/response-templates', JSON.parse(body), key);
          if (attempts.length === 1) return HttpResponse.error();
          return HttpResponse.json(reply?.body as Record<string, unknown>, {
            status: reply?.status,
          });
        }),
      );
      const { telegram } = startApp('/jobs/responses/templates');
      await waitFor(() => expect(mainButton(telegram)?.text).toBe('Новый шаблон'));
      await pressMainButton(telegram);
      const sheet = screen.getByRole('dialog', { name: 'Новый шаблон' });
      await type(within(sheet).getByRole('textbox', { name: 'Название' }), 'По фото');
      await type(
        within(sheet).getByRole('textbox', { name: 'Сообщение клиенту' }),
        'Пришлите фото — назову точную цену.',
      );
      await click(within(sheet).getByRole('radio', { name: 'Договорная' }));
      await pressMainButton(telegram);

      expect(
        await screen.findByText('Не получилось сохранить шаблон. Попробуйте ещё раз.'),
      ).toBeTruthy();
      expect(backend.templates).toHaveLength(1);
      if (edited) {
        await type(within(sheet).getByRole('textbox', { name: 'Название' }), 'По описанию');
      }
      await pressMainButton(telegram);

      await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
      expect(attempts).toHaveLength(2);
      expect(attempts[0]?.key).toBeTruthy();
      expect(attempts[0]?.key === attempts[1]?.key).toBe(!edited);
      expect(backend.templates).toHaveLength(edited ? 2 : 1);
      expect(
        await screen.findByRole('article', { name: edited ? 'По описанию' : 'По фото' }),
      ).toBeTruthy();
    },
  );

  it('lists templates, makes one primary and refuses a third', async () => {
    const backend = withJobs((it) => {
      it.templates = templatesFixture();
    });
    const { telegram } = startApp('/jobs/responses/templates');

    const first = await screen.findByRole('article', { name: 'Могу сегодня' });
    expect(within(first).getByText('Основной')).toBeTruthy();
    expect(within(first).getByText(/^от 2\s000\sRSD · сегодня$/u)).toBeTruthy();
    const second = screen.getByRole('article', { name: 'Свой инструмент' });
    expect(within(second).getByText('В боте')).toBeTruthy();
    expect(screen.getByText('Шаблонов: 2 из 2')).toBeTruthy();

    await click(within(second).getByRole('button', { name: 'Сделать основным' }));

    await waitFor(() =>
      expect(backend.templates.map((item) => item.title)).toEqual([
        'Свой инструмент',
        'Могу сегодня',
      ]),
    );
    await waitFor(() => expect(cardTitles()).toEqual(['Свой инструмент', 'Могу сегодня']));
    await waitFor(() => expect(mainButton(telegram)?.text).toBe('Новый шаблон'));
    await pressMainButton(telegram);
    expect(screen.getByText('Шаблонов уже 2 — удалите один, чтобы добавить новый')).toBeTruthy();
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('deletes a template and creates a new one in the sheet', async () => {
    const backend = withJobs((it) => {
      it.templates = templatesFixture();
    });
    const { telegram } = startApp('/jobs/responses/templates', { popupAnswer: 'ok' });
    const first = await screen.findByRole('article', { name: 'Могу сегодня' });

    await click(within(first).getByRole('button', { name: 'Изменить' }));
    const sheet = screen.getByRole('dialog', { name: 'Шаблон отклика' });
    expect(
      (within(sheet).getByRole('textbox', { name: 'Название' }) as HTMLInputElement).value,
    ).toBe('Могу сегодня');
    await click(within(sheet).getByRole('button', { name: 'Удалить шаблон' }));

    await waitFor(() =>
      expect(backend.templates.map((item) => item.title)).toEqual(['Свой инструмент']),
    );
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    expect(await screen.findByText('Шаблонов: 1 из 2')).toBeTruthy();
    const kept = screen.getByRole('article', { name: 'Свой инструмент' });
    expect(within(kept).getByText('Основной')).toBeTruthy();

    await waitFor(() => expect(mainButton(telegram)?.text).toBe('Новый шаблон'));
    await pressMainButton(telegram);
    const created = screen.getByRole('dialog', { name: 'Новый шаблон' });
    await waitFor(() => expect(mainButton(telegram)?.text).toBe('Сохранить шаблон'));
    await pressMainButton(telegram);
    expect(within(created).getByText('Назовите шаблон')).toBeTruthy();
    await type(within(created).getByRole('textbox', { name: 'Название' }), 'По фото');
    await type(
      within(created).getByRole('textbox', { name: 'Сообщение клиенту' }),
      'Пришлите фото — назову точную цену.',
    );
    await click(within(created).getByRole('radio', { name: 'Договорная' }));
    await pressMainButton(telegram);

    await waitFor(() =>
      expect(backend.templates.map((item) => item.title)).toEqual(['Свой инструмент', 'По фото']),
    );
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    expect(await screen.findByRole('article', { name: 'По фото' })).toBeTruthy();
  });
});
