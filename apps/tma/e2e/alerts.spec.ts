// Подписки на заявки S18 и S19 (DEVELOPMENT_PLAN 5.7) на фейке backend: ссылка `m_alerts` (кнопка
// бота `/alerts`) открывает список, как на артборде, → «Новая подписка» → форма S19 с «Мастер на
// час», «3 км» от Лимана, бюджетом от 2 000 и русским языком, как на артборде → «Сохранить
// подписку» — снова список, уже с тремя. Скриншоты × тема × язык, axe-core. Канал бота на
// снимках открыт (запроса нет, как на артбордах); отдельный сценарий — выключенный канал: после
// создания подписки «Присылать новые заявки в бот?» → requestWriteAccess → канал включён. Имена
// скриншотов начинаются с кода артборда (make design-compare).
import { encodeStartParam } from '@sosed/links';
import { expect, test } from '@playwright/test';

import { E2E_NOW, ME, NOTIFICATION_SETTINGS, WRITE_ACCESS } from '../src/testing/fixtures.ts';
import { JobsBackend, alertsFixture } from '../src/testing/jobsBackend.ts';
import { sentRequests } from './api.ts';
import { THEMES, expectNoAxeViolations, open, pressTelegram, real } from './support.ts';

const LOCALES = [
  {
    locale: 'ru',
    telegram: 'ru',
    title: 'Подписки на заявки',
    toggle: 'Присылать заявки по подписке «Мастер на час»',
    form: 'Новая подписка',
    handyman: 'Мастер на час',
    km: '3 км',
    radius: 'Радиус от вас · Лиман',
    budget: 'Бюджет от',
    language: /Язык общения/,
    russian: 'Русский',
    saved: 'Мастер на час',
    botTitle: 'Присылать новые заявки в бот?',
    allow: 'Присылать в Telegram',
    allowed: 'Новые заявки придут в Telegram',
  },
  {
    locale: 'sr-Latn',
    telegram: 'sr',
    title: 'Pretplate na zahteve',
    toggle: 'Šalji zahteve po pretplati „Majstor na sat“',
    form: 'Nova pretplata',
    handyman: 'Majstor na sat',
    km: '3 km',
    radius: 'Radijus od vas · Liman',
    budget: 'Budžet od',
    language: /Jezik sporazumevanja/,
    russian: 'Ruski',
    saved: 'Majstor na sat',
    botTitle: 'Slati nove zahteve u bot?',
    allow: 'Šalji u Telegram',
    allowed: 'Novi zahtevi stižu u Telegram',
  },
] as const;

const ALERTS_LINK = encodeStartParam({ type: 'mine', section: 'alerts' });

for (const theme of THEMES) {
  for (const l of LOCALES) {
    test(`S18 и S19 ${theme} ${l.locale}: подписки и новая подписка`, async ({ page }) => {
      await page.clock.setFixedTime(new Date(E2E_NOW));
      const jobs = new JobsBackend();
      jobs.alerts = alertsFixture();
      const watch = await open(page, `theme=${theme}&lang=${l.telegram}&start=${ALERTS_LINK}`, {
        signedIn: true,
        me: { ...ME, intent: 'pro', ui_locale: l.locale },
        jobs,
        notificationSettings: { ...NOTIFICATION_SETTINGS, telegram: WRITE_ACCESS },
      });
      /** Снимок экрана: до него — ни ошибок, ни неописанных запросов, после — axe-core. */
      const snap = async (name: string) => {
        expect(real(watch.problems)).toEqual([]);
        expect(watch.unexpectedApi).toEqual([]);
        await expect(page).toHaveScreenshot(name, { fullPage: true });
        await expectNoAxeViolations(page);
        watch.problems.length = 0;
      };

      await expect(page.getByRole('heading', { name: l.title, level: 1 })).toBeVisible();
      await expect(page.getByRole('switch', { name: l.toggle })).toBeVisible();
      await snap(`S18-alerts-${theme}-${l.locale}.png`);

      await pressTelegram(page, 'main_button_pressed');
      await expect(page.getByRole('heading', { name: l.form, level: 1 })).toBeVisible();
      await page.getByRole('button', { name: l.handyman }).click();
      await page.getByRole('button', { name: l.km }).click();
      await expect(page.getByText(l.radius)).toBeVisible();
      await page.getByRole('textbox', { name: l.budget }).fill('2000');
      await page.getByRole('button', { name: l.language }).click();
      await page.getByRole('button', { name: l.russian }).click();
      await expect(page.getByRole('button', { name: l.language })).toContainText(l.russian);
      await snap(`S19-alert-form-${theme}-${l.locale}.png`);

      await pressTelegram(page, 'main_button_pressed');
      await expect(page.getByRole('heading', { name: l.title, level: 1 })).toBeVisible();
      await expect(page.getByRole('switch', { name: l.toggle })).toHaveCount(2);
      expect(jobs.alerts).toHaveLength(3);
      expect(new Set(jobs.alertWrites.map((write) => write.key)).size).toBe(1);
    });
  }
}

test('S18 при выключенном канале бота после новой подписки просит разрешение', async ({ page }) => {
  await page.clock.setFixedTime(new Date(E2E_NOW));
  const jobs = new JobsBackend();
  const sent = sentRequests();
  const l = LOCALES[0];
  const watch = await open(page, `theme=light&lang=ru&start=${ALERTS_LINK}`, {
    signedIn: true,
    jobs,
    sent,
  });

  await expect(page.getByRole('heading', { name: l.title, level: 1 })).toBeVisible();
  await pressTelegram(page, 'main_button_pressed');
  await expect(page.getByRole('heading', { name: l.form, level: 1 })).toBeVisible();
  await page.getByRole('button', { name: l.handyman }).click();
  await pressTelegram(page, 'main_button_pressed');

  await expect(page.getByRole('switch', { name: l.toggle })).toBeVisible();
  await expect(page.getByRole('heading', { name: l.botTitle })).toBeVisible();
  await page.getByRole('button', { name: l.allow }).click();

  await expect(page.getByText(l.allowed)).toBeVisible();
  expect(sent.writeAccess).toBe(1);
  expect(jobs.alerts).toHaveLength(1);
  expect(real(watch.problems)).toEqual([]);
  expect(watch.unexpectedApi).toEqual([]);
});
