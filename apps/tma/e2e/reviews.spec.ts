// Отзывы клиента и история сделок (DEVELOPMENT_PLAN 7.3) на фейке backend. S27 — по ссылке `d_`
// из бота на завершённую сделку → MainButton «Оставить отзыв» → четыре звезды «Хорошо»,
// «Качество» и «Пунктуальность», текст — как на артборде; «Опубликовать отзыв» — отзыв ждёт
// проверки. S28 — из профиля «Сделки и отзывы»: активная, завершённая с отзывом, завершённая без
// отзыва и отменённая, как на артборде; вкладка «Отзывы» — отзыв обо мне с «Ответить». Скриншоты
// × тема × язык, axe-core; имена скриншотов начинаются с кода артборда.
import type { DealCardOut } from '@sosed/api-client';
import { encodeStartParam } from '@sosed/links';
import { expect, test } from '@playwright/test';

import { E2E_NOW, ME } from '../src/testing/fixtures.ts';
import {
  JobsBackend,
  completedDealFixture,
  dealCardFixture,
  myJobsFixture,
  receivedReviewFixture,
  responseCardsFixture,
} from '../src/testing/jobsBackend.ts';
import {
  THEMES,
  expectNoAxeViolations,
  open,
  openProfile,
  pressTelegram,
  real,
} from './support.ts';

const LOCALES = [
  {
    locale: 'ru',
    telegram: 'ru',
    title: 'Как всё прошло?',
    stars: '4 звезды',
    grade: 'Хорошо',
    quality: 'Качество',
    punctuality: 'Пунктуальность',
    body: 'Отзыв',
    text: 'Приехал вовремя, аккуратно повесил и подключил люстру, убрал за собой. Рекомендую.',
    sent: 'Спасибо! Отзыв появится после проверки.',
    profile: 'Профиль',
    history: 'Сделки и отзывы',
    active: 'Активные',
    finished: 'Завершённые',
    reviews: 'Отзывы',
    reply: 'Ответить',
  },
  {
    locale: 'sr-Latn',
    telegram: 'sr',
    title: 'Kako je prošlo?',
    stars: '4 zvezdice',
    grade: 'Dobro',
    quality: 'Kvalitet',
    punctuality: 'Tačnost',
    body: 'Utisak',
    text: 'Došao je na vreme, uredno okačio i povezao luster, počistio za sobom. Preporučujem.',
    sent: 'Hvala! Utisak će se pojaviti posle provere.',
    profile: 'Profil',
    history: 'Dogovori i utisci',
    active: 'Aktivni',
    finished: 'Završeni',
    reviews: 'Utisci',
    reply: 'Odgovori',
  },
] as const;

const DAY_MS = 24 * 60 * 60 * 1000;

/** Сделки клиента, как на артборде S28: идущая люстра с Алексеем, уборка с оставленным отзывом,
 *  комод без отзыва (его ещё можно оставить) и смеситель, отменённый исполнителем. */
function historyWorld() {
  const [chandelier, cleaning, repair] = myJobsFixture();
  const [aleksey, ivan, nikola] = responseCardsFixture();
  if (!chandelier || !cleaning || !repair || !aleksey || !ivan || !nikola) {
    throw new Error('fixtures');
  }
  const at = (days: number) => new Date(Date.parse(E2E_NOW) - days * DAY_MS).toISOString();
  const reviewed = completedDealFixture(repair, ivan);
  const cancelled = dealCardFixture(
    cleaning,
    { ...nikola, id: `${nikola.id.slice(0, -1)}9` },
    'client',
  );
  const deals: DealCardOut[] = [
    {
      ...cancelled,
      title: 'Заменить смеситель',
      status: 'cancelled',
      cancel_reason: 'plans_changed',
      cancelled_by_me: false,
      timeline: { ...cancelled.timeline, cancelled_at: at(38) },
    },
    {
      ...reviewed,
      my_review: { id: '01a0e004-0000-7000-8000-0000000000bb', status: 'published', rating: 5 },
      review_until: null,
      timeline: { ...reviewed.timeline, completed_at: at(21) },
    },
    { ...completedDealFixture(cleaning, nikola), title: 'Собрать комод MALM' },
    dealCardFixture(chandelier, aleksey, 'client'),
  ];
  const jobs = new JobsBackend().seedMine();
  for (const deal of deals) jobs.deals.set(deal.id, deal);
  jobs.received.push(receivedReviewFixture());
  return jobs;
}

for (const theme of THEMES) {
  for (const l of LOCALES) {
    test(`S27 ${theme} ${l.locale}: отзыв по завершённой сделке из бота`, async ({ page }) => {
      await page.clock.setFixedTime(new Date(E2E_NOW));
      const [chandelier] = myJobsFixture();
      const [aleksey] = responseCardsFixture();
      if (!chandelier || !aleksey) throw new Error('fixtures');
      const jobs = new JobsBackend().seedMine();
      const deal = completedDealFixture(chandelier, aleksey);
      jobs.deals.set(deal.id, deal);
      const start = encodeStartParam({ type: 'deal', id: deal.id });
      const watch = await open(page, `theme=${theme}&lang=${l.telegram}&start=${start}`, {
        signedIn: true,
        me: { ...ME, ui_locale: l.locale },
        jobs,
      });

      // S26 завершённой сделки: MainButton «Оставить отзыв» — нативная, в DOM её нет
      await expect(page.getByRole('heading', { name: 'Повесить люстру', level: 1 })).toBeVisible();
      await pressTelegram(page, 'main_button_pressed');
      await expect(page.getByRole('heading', { name: l.title, level: 1 })).toBeVisible();
      await page.getByRole('radio', { name: l.stars }).click();
      await expect(page.getByText(l.grade, { exact: true })).toBeVisible();
      await page.getByRole('button', { name: l.quality }).click();
      await page.getByRole('button', { name: l.punctuality }).click();
      await page.getByRole('textbox', { name: l.body }).fill(l.text);
      // фокус уходит из поля: каретка мигала бы на снимке
      await page.getByRole('radio', { name: l.stars }).focus();
      expect(real(watch.problems)).toEqual([]);
      expect(watch.unexpectedApi).toEqual([]);
      await expect(page).toHaveScreenshot(`S27-review-${theme}-${l.locale}.png`, {
        fullPage: true,
      });
      await expectNoAxeViolations(page);

      // «Опубликовать отзыв» — MainButton: отзыв уходит на проверку
      await pressTelegram(page, 'main_button_pressed');
      await expect(page.getByText(l.sent)).toBeVisible();
      expect(jobs.reviews.get(deal.id)).toMatchObject({
        rating: 4,
        criteria: { quality: 4, punctuality: 4 },
        body: l.text,
      });
    });

    test(`S28 ${theme} ${l.locale}: сделки и отзывы из профиля`, async ({ page }) => {
      await page.clock.setFixedTime(new Date(E2E_NOW));
      const watch = await open(page, `theme=${theme}&lang=${l.telegram}`, {
        signedIn: true,
        me: { ...ME, ui_locale: l.locale },
        jobs: historyWorld(),
      });
      const snap = async (name: string) => {
        expect(real(watch.problems)).toEqual([]);
        expect(watch.unexpectedApi).toEqual([]);
        await expect(page).toHaveScreenshot(name, { fullPage: true });
        await expectNoAxeViolations(page);
        watch.problems.length = 0;
      };

      await openProfile(page, l.profile);
      await page.getByRole('link', { name: l.history }).click();
      await expect(page.getByRole('heading', { name: l.history, level: 1 })).toBeVisible();
      await expect(page.getByRole('heading', { name: l.active })).toBeVisible();
      await expect(page.getByRole('heading', { name: l.finished })).toBeVisible();
      await expect(page.getByRole('article')).toHaveCount(4);
      await snap(`S28-history-${theme}-${l.locale}.png`);

      await page
        .getByRole('radiogroup', { name: l.history })
        .getByRole('radio', { name: l.reviews })
        .click();
      const review = page.getByRole('article', { name: 'Елена К.' });
      await expect(review.getByRole('button', { name: l.reply })).toBeVisible();
      await snap(`S28-history-reviews-${theme}-${l.locale}.png`);
    });
  }
}
