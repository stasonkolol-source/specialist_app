// S43 Настройки и S47 Помощь (DEVELOPMENT_PLAN 4.9): из профиля S31, скриншоты × тема × язык и
// axe-core. Настройки уведомлений — как на артборде (новости — только в приложении, бот может
// писать), контакт поддержки задан (Q25). Язык пишется в PATCH /me и сразу меняет интерфейс,
// отметка уведомления — PUT /me/notification-settings, шестерёнка S42 ведёт в S43. Имена
// скриншотов начинаются с кода артборда: make design-compare кладёт их рядом с эталоном.
import type { NotificationSettingsOut } from '@sosed/api-client';
import { expect, test } from '@playwright/test';

import { CLIENT_CONFIG, ME, NOTIFICATION_SETTINGS, WRITE_ACCESS } from '../src/testing/fixtures.ts';
import { sentRequests } from './api.ts';
import { THEMES, expectNoAxeViolations, open, openProfile, real } from './support.ts';

/** Как на артборде S43: новости — только в приложении, бот пишет (баннера S42 нет). */
const ARTBOARD_SETTINGS: NotificationSettingsOut = {
  ...NOTIFICATION_SETTINGS,
  groups: NOTIFICATION_SETTINGS.groups.map((row) =>
    row.group === 'marketing' ? { ...row, in_app: true } : row,
  ),
  telegram: WRITE_ACCESS,
};

const SUPPORT_CONFIG = { ...CLIENT_CONFIG, support_username: 'sosedi_support' };

const LOCALES = [
  {
    locale: 'ru',
    telegram: 'ru',
    profile: 'Профиль',
    settings: 'Настройки',
    news: 'Новости «Соседей» — в боте',
    city: /^Город\s*Нови-Сад/,
    help: 'Помощь',
    faq: 'Почему откликов не больше 5?',
  },
  {
    locale: 'sr-Latn',
    telegram: 'sr',
    profile: 'Profil',
    settings: 'Podešavanja',
    news: 'Novosti aplikacije „Sosedi“ — u botu',
    city: /^Grad\s*Novi Sad/,
    help: 'Pomoć',
    faq: 'Zašto nema više od 5 ponuda?',
  },
] as const;

for (const theme of THEMES) {
  for (const l of LOCALES) {
    test(`S43 настройки ${theme} ${l.locale}: язык, город, уведомления, приватность`, async ({
      page,
    }) => {
      const watch = await open(page, `theme=${theme}&lang=${l.telegram}`, {
        signedIn: true,
        me: { ...ME, ui_locale: l.locale },
        notificationSettings: ARTBOARD_SETTINGS,
      });
      await openProfile(page, l.profile);
      await page.getByRole('link', { name: l.settings, exact: true }).click();

      await expect(page.getByRole('heading', { name: l.settings, level: 1 })).toBeVisible();
      await expect(page.getByRole('button', { name: l.city })).toBeVisible();
      await expect(page.getByRole('checkbox', { name: l.news })).toHaveAttribute(
        'aria-checked',
        'false',
      );
      expect(real(watch.problems)).toEqual([]);
      expect(watch.unexpectedApi).toEqual([]);
      await expect(page).toHaveScreenshot(`S43-settings-${theme}-${l.locale}.png`, {
        fullPage: true,
      });
      await expectNoAxeViolations(page);
    });

    test(`S47 помощь ${theme} ${l.locale}: безопасность, вопросы, правила`, async ({ page }) => {
      const watch = await open(page, `theme=${theme}&lang=${l.telegram}`, {
        signedIn: true,
        me: { ...ME, ui_locale: l.locale },
        config: SUPPORT_CONFIG,
      });
      await openProfile(page, l.profile);
      await page.getByRole('link', { name: l.help, exact: true }).click();

      await expect(page.getByRole('heading', { name: l.help, level: 1 })).toBeVisible();
      await expect(page.getByRole('button', { name: l.faq })).toHaveAttribute(
        'aria-expanded',
        'true',
      );
      expect(real(watch.problems)).toEqual([]);
      expect(watch.unexpectedApi).toEqual([]);
      await expect(page).toHaveScreenshot(`S47-help-${theme}-${l.locale}.png`, {
        fullPage: true,
      });
      await expectNoAxeViolations(page);
    });
  }
}

// UXM-15: переключатель 51×31 и галочки отвечали только в своих рамках. Зона нажатия — не меньше
// 44 px по высоте при том же виде: точка в 6 px над и под переключателем — всё ещё он
test('S43: зона нажатия переключателей — не меньше 44 px по высоте', async ({ page }) => {
  await open(page, 'theme=light&lang=ru', {
    signedIn: true,
    notificationSettings: ARTBOARD_SETTINGS,
  });
  await openProfile(page);
  await page.getByRole('link', { name: /^Уведомления/ }).click();
  await page.getByRole('link', { name: 'Настройки уведомлений' }).click();
  const switches = page.getByRole('switch');
  await expect(switches.first()).toBeVisible();
  for (const control of await switches.all()) {
    // по центру экрана: точки над и под переключателем — в пределах окна, не под таббаром
    await control.evaluate((element) => element.scrollIntoView({ block: 'center' }));
    const box = await control.boundingBox();
    if (!box) throw new Error('нет переключателя');
    expect(box.height).toBeLessThan(44);
    const hit = await control.evaluate(
      (element, { x, ys }) => {
        return ys.map((y) => element.contains(document.elementFromPoint(x, y)));
      },
      { x: box.x + box.width / 2, ys: [box.y - 6, box.y + box.height + 6] },
    );
    expect(hit).toEqual([true, true]);
  }
});

test('S43: язык — PATCH /me и сразу интерфейс, отметка уведомления — PUT, вход из S42', async ({
  page,
}) => {
  const sent = sentRequests();
  const watch = await open(page, 'theme=light&lang=ru', {
    signedIn: true,
    notificationSettings: ARTBOARD_SETTINGS,
    sent,
  });
  await openProfile(page);
  await page.getByRole('link', { name: /^Уведомления/ }).click();
  await page.getByRole('link', { name: 'Настройки уведомлений' }).click();
  await expect(page.getByRole('heading', { name: 'Настройки', level: 1 })).toBeVisible();

  await page.getByRole('checkbox', { name: 'Сообщения — в боте' }).click();
  await expect(page.getByRole('checkbox', { name: 'Сообщения — в боте' })).toHaveAttribute(
    'aria-checked',
    'false',
  );
  await expect.poll(() => sent.settings.length).toBe(1);
  expect(sent.settings[0]?.groups.find((row) => row.group === 'messages')).toEqual({
    group: 'messages',
    telegram: false,
    in_app: true,
  });

  const patch = page.waitForRequest(
    (r) => r.method() === 'PATCH' && r.url().endsWith('/api/v1/me'),
  );
  await page.getByRole('radio', { name: 'Srpski (latinica)' }).click();

  expect((await patch).postDataJSON()).toEqual({ ui_locale: 'sr-Latn' });
  await expect(page.getByRole('heading', { name: 'Podešavanja', level: 1 })).toBeVisible();
  await expect(page.locator('html')).toHaveAttribute('lang', 'sr-Latn');
  await expect(page.getByRole('radio', { name: 'Srpski (latinica)' })).toHaveAttribute(
    'aria-checked',
    'true',
  );
  expect(real(watch.problems)).toEqual([]);
  expect(watch.unexpectedApi).toEqual([]);
});
