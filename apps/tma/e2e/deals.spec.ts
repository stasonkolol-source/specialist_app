// Выбор исполнителя и сделка S24–S26 (DEVELOPMENT_PLAN 6.2) на фейке backend: своя заявка S23 →
// отклик Алексея S24 → шторка выбора S25 → сделка S26 («Договорились», исполнитель, адрес,
// таймлайн, памятка). Завершённая сделка S26 по ссылке `d_` — «Заказать снова»: прямой диалог
// с Алексеем, где можно договориться. Спор S52 (6.1c) по ссылке `p_` из бота: форма как на
// артборде → «Отправить» → «Ждём ответа»; вторая сторона — сообщение, срок и форма ответа.
// Скриншоты × тема × язык, axe-core. Имена скриншотов начинаются с кода артборда: make
// design-compare кладёт их рядом с эталоном.
import { expect, test } from '@playwright/test';
import { encodeStartParam } from '@sosed/links';

import { ChatBackend } from '../src/testing/chatBackend.ts';
import { E2E_NOW, ME } from '../src/testing/fixtures.ts';
import {
  JobsBackend,
  completedDealFixture,
  dealCardFixture,
  myJobsFixture,
  responseCardsFixture,
} from '../src/testing/jobsBackend.ts';
import { ProfileBackend } from '../src/testing/profileBackend.ts';
import {
  THEMES,
  expectNoAxeViolations,
  open,
  openTab,
  pressTelegram,
  real,
  telegramButton,
} from './support.ts';

const LOCALES = [
  {
    locale: 'ru',
    telegram: 'ru',
    tab: 'Заявки',
    mine: 'Мои заявки',
    offer: 'Предложение',
    choose: 'Выбрать исполнителем',
    confirm: 'Выбрать этого исполнителя?',
    status: 'Статус',
    orderAgain: 'Заказать снова',
    agree: 'Договориться',
  },
  {
    locale: 'sr-Latn',
    telegram: 'sr',
    tab: 'Zahtevi',
    mine: 'Moji zahtevi',
    offer: 'Ponuda',
    choose: 'Izaberi izvođača',
    confirm: 'Izabrati ovog izvođača?',
    status: 'Status',
    orderAgain: 'Naruči ponovo',
    agree: 'Dogovorite se',
  },
] as const;

for (const theme of THEMES) {
  for (const l of LOCALES) {
    test(`S24–S26 ${theme} ${l.locale}: отклик, выбор, сделка`, async ({ page }) => {
      await page.clock.setFixedTime(new Date(E2E_NOW));
      const watch = await open(page, `theme=${theme}&lang=${l.telegram}`, {
        signedIn: true,
        me: { ...ME, ui_locale: l.locale },
        jobs: new JobsBackend().seedMine(),
      });
      const snap = async (name: string) => {
        expect(real(watch.problems)).toEqual([]);
        expect(watch.unexpectedApi).toEqual([]);
        await expect(page).toHaveScreenshot(name, { fullPage: true });
        await expectNoAxeViolations(page);
        watch.problems.length = 0;
      };

      // вкладка открывает «Ленту», свои заявки — сегментом «Мои заявки»
      await openTab(page, l.tab);
      await page.getByRole('link', { name: l.mine }).click();
      await page.getByRole('link', { name: /Повесить люстру/ }).click();
      await page.getByRole('link', { name: /^Алексей Морозов/ }).click();
      await expect(page.getByRole('heading', { name: 'Алексей Морозов', level: 1 })).toBeVisible();
      await expect(page.getByRole('region', { name: l.offer })).toBeVisible();
      await snap(`S24-response-${theme}-${l.locale}.png`);

      // «Выбрать исполнителем» — MainButton mock-клиента: нативная, в DOM её нет
      await pressTelegram(page, 'main_button_pressed', { text: l.choose });
      await expect(page.getByRole('dialog', { name: l.confirm })).toBeVisible();
      await snap(`S25-confirm-choice-${theme}-${l.locale}.png`);
      // подтверждение в шторке — её MainButton (видна и активна), «Написать» экрана спрятана (MU-2)
      await expect
        .poll(() => telegramButton(page, 'secondary_button_pressed'))
        .toMatchObject({
          is_visible: false,
        });
      const accepted = page.waitForResponse(
        (r) => /\/responses\/[^/]+\/accept$/.test(r.url()) && r.status() === 200,
      );
      await pressTelegram(page, 'main_button_pressed', { text: l.choose });
      await accepted;
      await expect(page.getByRole('heading', { name: 'Повесить люстру', level: 1 })).toBeVisible();
      await expect(page.getByRole('region', { name: l.status })).toBeVisible();
      await snap(`S26-deal-${theme}-${l.locale}.png`);
    });
  }
}

for (const theme of THEMES) {
  for (const l of LOCALES) {
    test(`S26 ${theme} ${l.locale}: завершённая сделка — заказать снова`, async ({ page }) => {
      await page.clock.setFixedTime(new Date(E2E_NOW));
      const [job] = myJobsFixture();
      const [card] = responseCardsFixture();
      if (!job || !card) throw new Error('fixtures');
      const jobs = new JobsBackend().seedMine();
      const deal = completedDealFixture(job, card);
      jobs.deals.set(deal.id, deal);
      const chat = new ChatBackend().seed();
      const start = encodeStartParam({ type: 'deal', id: deal.id });
      const watch = await open(page, `theme=${theme}&lang=${l.telegram}&start=${start}`, {
        signedIn: true,
        me: { ...ME, ui_locale: l.locale },
        jobs,
        chat,
      });

      await expect(page.getByRole('heading', { name: 'Повесить люстру', level: 1 })).toBeVisible();
      await expect(page.getByRole('button', { name: l.orderAgain })).toBeVisible();
      expect(real(watch.problems)).toEqual([]);
      expect(watch.unexpectedApi).toEqual([]);
      await expect(page).toHaveScreenshot(`S26-deal-completed-${theme}-${l.locale}.png`, {
        fullPage: true,
      });
      await expectNoAxeViolations(page);

      // прямой диалог с Алексеем: в шапке — «Договориться»
      await page.getByRole('button', { name: l.orderAgain }).click();
      await expect(page.getByRole('main').getByRole('button', { name: l.agree })).toBeVisible();
      expect(chat.starts).toEqual([{ profile_id: card.performer.profile_id }]);
    });
  }
}

const DISPUTE_LOCALES = [
  {
    locale: 'ru',
    telegram: 'ru',
    title: 'Проблема со сделкой',
    what: 'Что случилось?',
    noShow: 'Не пришёл',
    describe: 'Опишите, что произошло',
    text: 'Договорились на 19:00. В 19:40 мастера всё ещё нет, на сообщения не отвечает.',
    waiting: 'Ждём ответа',
    theirs: 'Сообщение второй стороны',
    answer: 'Ваш ответ',
  },
  {
    locale: 'sr-Latn',
    telegram: 'sr',
    title: 'Problem sa dogovorom',
    what: 'Šta se desilo?',
    noShow: 'Nije došao',
    describe: 'Opišite šta se desilo',
    text: 'Dogovorili smo se za 19:00. U 19:40 majstora još nema i ne odgovara na poruke.',
    waiting: 'Čekamo odgovor',
    theirs: 'Poruka druge strane',
    answer: 'Vaš odgovor',
  },
] as const;

/** Идущая сделка клиента с Алексеем (S26) и ссылка `p_` на её спор — как в кнопке бота. */
function disputeWorld() {
  const [job] = myJobsFixture();
  const [card] = responseCardsFixture();
  if (!job || !card) throw new Error('fixtures');
  const jobs = new JobsBackend().seedMine();
  const profile = new ProfileBackend();
  jobs.media = profile.media;
  const deal = dealCardFixture(job, card, 'client');
  jobs.deals.set(deal.id, deal);
  return { jobs, profile, deal, start: encodeStartParam({ type: 'dispute', id: deal.id }) };
}

for (const theme of THEMES) {
  for (const l of DISPUTE_LOCALES) {
    test(`S52 ${theme} ${l.locale}: спор из бота, форма и «Ждём ответа»`, async ({ page }) => {
      await page.clock.setFixedTime(new Date(E2E_NOW));
      const { jobs, profile, deal, start } = disputeWorld();
      const watch = await open(page, `theme=${theme}&lang=${l.telegram}&start=${start}`, {
        signedIn: true,
        me: { ...ME, ui_locale: l.locale },
        jobs,
        profile,
      });
      const snap = async (name: string) => {
        expect(real(watch.problems)).toEqual([]);
        expect(watch.unexpectedApi).toEqual([]);
        await expect(page).toHaveScreenshot(name, { fullPage: true });
        await expectNoAxeViolations(page);
        watch.problems.length = 0;
      };

      // «Есть проблема» под «Работа выполнена?» — сразу S52, не S26
      await expect(page.getByRole('heading', { name: l.title, level: 1 })).toBeVisible();
      const kinds = page.getByRole('radiogroup', { name: l.what });
      await kinds.getByRole('radio', { name: l.noShow }).click();
      await page.getByRole('textbox', { name: l.describe }).fill(l.text);
      await snap(`S52-dispute-${theme}-${l.locale}.png`);

      // «Отправить» — MainButton mock-клиента: спор сразу на экране
      await pressTelegram(page, 'main_button_pressed');
      await expect(page.getByText(l.waiting, { exact: true })).toBeVisible();
      expect(jobs.decisions).toEqual([{ id: deal.id, action: 'dispute', reason: 'no_show' }]);
      await snap(`S52-dispute-open-${theme}-${l.locale}.png`);
    });

    test(`S52 ${theme} ${l.locale}: вторая сторона отвечает`, async ({ page }) => {
      await page.clock.setFixedTime(new Date(E2E_NOW));
      const { jobs, profile, deal, start } = disputeWorld();
      jobs.deals.set(deal.id, {
        ...deal,
        status: 'disputed',
        dispute: {
          id: '0199df00-0000-7000-8000-0000000000d1',
          deal_id: deal.id,
          deal_status: 'disputed',
          status: 'open',
          kind: 'no_show',
          opened_by_me: true,
          description: l.text,
          photos: [],
          respond_by: new Date(Date.parse(E2E_NOW) + 48 * 60 * 60 * 1000).toISOString(),
          response: null,
          response_photos: [],
          responded_at: null,
          unanswered_at: null,
          withdrawn_at: null,
          outcome: null,
          reason_code: null,
          resolved_at: null,
          created_at: E2E_NOW,
        },
      });
      jobs.dealRole = 'performer';
      const watch = await open(page, `theme=${theme}&lang=${l.telegram}&start=${start}`, {
        signedIn: true,
        me: { ...ME, ui_locale: l.locale },
        jobs,
        profile,
      });

      await expect(page.getByRole('region', { name: l.theirs })).toBeVisible();
      await expect(page.getByRole('textbox', { name: l.answer })).toBeVisible();
      expect(real(watch.problems)).toEqual([]);
      expect(watch.unexpectedApi).toEqual([]);
      await expect(page).toHaveScreenshot(`S52-dispute-answer-${theme}-${l.locale}.png`, {
        fullPage: true,
      });
      await expectNoAxeViolations(page);
    });
  }
}
