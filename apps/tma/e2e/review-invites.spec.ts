// «Отзывы до платформы» (DEVELOPMENT_PLAN 7.6а) на фейке backend. S55 — из кабинета S33: правила,
// «4 из 5 · осталось 1» и приглашения, как на артборде (два опубликованных отзыва, один на
// модерации, ссылка Андрею ждёт отзыва); MainButton «Создать ссылку» → «Кому» → готовая ссылка.
// S56 — по ссылке `ri_` из Telegram: кто просит отзыв, пять звёзд «Отлично», «Что делал специалист»,
// текст и «Подтверждаю…», как на артборде; «Отправить отзыв» — отзыв ждёт модератора. Скриншоты ×
// тема × язык, axe-core; имена скриншотов начинаются с кода артборда.
import { encodeStartParam } from '@sosed/links';
import { expect, test } from '@playwright/test';

import { E2E_NOW, FIRST_SERVICE, ME, PROFILE_FILLED } from '../src/testing/fixtures.ts';
import { InvitesBackend, invitesFixture } from '../src/testing/invitesBackend.ts';
import { ProfileBackend } from '../src/testing/profileBackend.ts';
import type { Watch } from './support.ts';
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
    tab: 'Профиль',
    card: /Кабинет специалиста/,
    row: /Отзывы до платформы/,
    invites: 'Отзывы до платформы',
    taken: '4 из 5 · осталось 1',
    newTitle: 'Новая ссылка',
    name: 'Кому',
    ready: 'Ссылка готова',
    title: 'Отзыв о прошлой работе',
    stars: '5 звёзд',
    grade: 'Отлично',
    work: 'Что делал специалист',
    workText: 'Проводка в ванной и светильники',
    body: 'Отзыв',
    text: 'Поменял проводку в ванной и повесил светильники. Всё сделал за день, объяснил, что и зачем.',
    confirm: /^Подтверждаю/,
    sent: 'Спасибо! Отзыв появится после проверки',
  },
  {
    locale: 'sr-Latn',
    telegram: 'sr',
    tab: 'Profil',
    card: /Kabinet stručnjaka/,
    row: /Utisci pre platforme/,
    invites: 'Utisci pre platforme',
    taken: '4 od 5 · preostalo 1',
    newTitle: 'Novi link',
    name: 'Kome',
    ready: 'Link je spreman',
    title: 'Utisak o ranijem poslu',
    stars: '5 zvezdica',
    grade: 'Odlično',
    work: 'Šta je stručnjak radio',
    workText: 'Instalacija u kupatilu i svetiljke',
    body: 'Utisak',
    text: 'Promenio je instalaciju u kupatilu i okačio svetiljke. Sve je uradio za jedan dan.',
    confirm: /^Potvrđujem/,
    sent: 'Hvala! Utisak će se pojaviti posle provere',
  },
] as const;

/** Снимок экрана: до него — ни ошибок, ни неописанных запросов, после — axe-core. Шторка —
 *  снимком окна, а не всей страницы, и axe-core — только внутри неё, как S46 и S54: под затемнением
 *  контраст экрана не проверяется. */
async function snap(
  page: Parameters<typeof expectNoAxeViolations>[0],
  watch: Watch,
  name: string,
  { sheet = false }: { sheet?: boolean } = {},
) {
  expect(real(watch.problems)).toEqual([]);
  expect(watch.unexpectedApi).toEqual([]);
  await expect(page).toHaveScreenshot(name, { fullPage: !sheet });
  await expectNoAxeViolations(page, sheet ? { include: '[role="dialog"]' } : {});
  // снимок вставляет стиль «без анимаций» — CSP приложения в WebKit его отклоняет и пишет в
  // консоль; дальше проверяем только то, что случилось после снимка
  watch.problems.length = 0;
}

for (const theme of THEMES) {
  for (const l of LOCALES) {
    test(`S55 ${theme} ${l.locale}: приглашения на отзыв до платформы из кабинета`, async ({
      page,
    }) => {
      await page.clock.setFixedTime(new Date(E2E_NOW));
      const invites = new InvitesBackend(invitesFixture(), { now: () => new Date(E2E_NOW) });
      const profile = new ProfileBackend({ ...PROFILE_FILLED, status: 'published' }, [
        FIRST_SERVICE,
      ], { invites }); // prettier-ignore
      const watch = await open(page, `theme=${theme}&lang=${l.telegram}`, {
        signedIn: true,
        me: { ...ME, ui_locale: l.locale },
        profile,
      });

      await openProfile(page, l.tab);
      await page.getByRole('link', { name: l.card }).click();
      await page.getByRole('link', { name: l.row }).click();
      await expect(page.getByRole('heading', { name: l.invites, level: 1 })).toBeVisible();
      await expect(page.getByText(l.taken)).toBeVisible();
      await expect(page.getByText('Андрей В.')).toBeVisible();
      await snap(page, watch, `S55-review-invites-${theme}-${l.locale}.png`);

      // MainButton «Создать ссылку» — нативная, в DOM её нет: шторка «Кому», затем готовая ссылка
      await pressTelegram(page, 'main_button_pressed');
      const sheet = page.getByRole('dialog', { name: l.newTitle });
      await sheet.getByRole('textbox', { name: l.name }).fill('Марко П.');
      await pressTelegram(page, 'main_button_pressed');
      await expect(page.getByRole('dialog', { name: l.ready })).toBeVisible();
      expect(invites.items[0]).toMatchObject({ client_name: 'Марко П.', status: 'waiting' });
      await snap(page, watch, `S55-review-invites-ready-${theme}-${l.locale}.png`, { sheet: true });
    });

    test(`S56 ${theme} ${l.locale}: отзыв по ссылке-приглашению из Telegram`, async ({ page }) => {
      await page.clock.setFixedTime(new Date(E2E_NOW));
      const [waiting] = invitesFixture();
      if (!waiting) throw new Error('fixtures');
      const invites = new InvitesBackend(invitesFixture());
      const start = encodeStartParam({ type: 'review_invite', id: waiting.token });
      const watch = await open(page, `theme=${theme}&lang=${l.telegram}&start=${start}`, {
        signedIn: true,
        me: { ...ME, ui_locale: l.locale },
        profile: new ProfileBackend(null, [], { invites }),
      });

      await expect(page.getByRole('heading', { name: l.title, level: 1 })).toBeVisible();
      await page.getByRole('radio', { name: l.stars }).click();
      await expect(page.getByText(l.grade, { exact: true })).toBeVisible();
      await page.getByRole('textbox', { name: l.work }).fill(l.workText);
      await page.getByRole('textbox', { name: l.body }).fill(l.text);
      await page.getByRole('checkbox', { name: l.confirm }).click();
      // фокус уходит из поля: каретка мигала бы на снимке
      await page.getByRole('radio', { name: l.stars }).focus();
      await snap(page, watch, `S56-invite-review-${theme}-${l.locale}.png`);

      // «Отправить отзыв» — MainButton: отзыв уходит модератору
      await pressTelegram(page, 'main_button_pressed');
      await expect(page.getByRole('heading', { name: l.sent })).toBeVisible();
      expect(invites.reviews.get(waiting.token)).toEqual({
        rating: 5,
        work_title: l.workText,
        body: l.text,
        confirmed: true,
      });
    });
  }
}
