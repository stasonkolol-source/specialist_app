// Задел «Вещи» (DEVELOPMENT_PLAN 7.5): S58 по артборду (скриншоты × тема, axe-core), «Сообщить о
// запуске» — сначала разрешение боту писать, потом группа `goods_launch` в PUT
// /me/notification-settings и «Готово!»; сегмент на S03 — только по флагу goods.segment (Q26: в
// бете выключен); отписка — переключатель на S43. Имена скриншотов начинаются с кода артборда.
import type { NotificationSettingsOut } from '@sosed/api-client';
import { expect, test } from '@playwright/test';

import { CLIENT_CONFIG, NOTIFICATION_SETTINGS } from '../src/testing/fixtures.ts';
import { sentRequests } from './api.ts';
import { THEMES, expectNoAxeViolations, open, openProfile, real } from './support.ts';

const SUBSCRIBED: NotificationSettingsOut = {
  ...NOTIFICATION_SETTINGS,
  groups: NOTIFICATION_SETTINGS.groups.map((row) =>
    row.group === 'goods_launch' ? { ...row, telegram: true, in_app: true } : row,
  ),
};

for (const theme of THEMES) {
  test(`S58 вещи — скоро ${theme} ru`, async ({ page }) => {
    const watch = await open(page, `theme=${theme}&lang=ru`, { signedIn: true });

    await page.getByRole('radio', { name: 'Вещи' }).click();

    await expect(page.getByRole('heading', { name: 'Вещи — скоро', level: 1 })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Сообщить о запуске' })).toBeEnabled();
    // кнопка в контенте: таббар виден, MainButton нет
    await expect(page.getByRole('navigation', { name: 'Разделы' })).toBeVisible();
    expect(real(watch.problems)).toEqual([]);
    expect(watch.unexpectedApi).toEqual([]);
    await expect(page).toHaveScreenshot(`S58-goods-soon-${theme}-ru.png`, { fullPage: true });
    await expectNoAxeViolations(page);
  });
}

test('S58: «Сообщить о запуске» — разрешение боту, подписка goods_launch, «Готово!»', async ({
  page,
}) => {
  const sent = sentRequests();
  const watch = await open(page, 'theme=light&lang=ru', { signedIn: true, sent });
  await page.getByRole('radio', { name: 'Вещи' }).click();

  await page.getByRole('button', { name: 'Сообщить о запуске' }).click();

  await expect(
    page
      .getByRole('status')
      .filter({ hasText: 'Готово! Бот напишет, когда раздел «Вещи» откроется.' }),
  ).toBeVisible();
  await expect(page.getByRole('button', { name: 'Сообщить о запуске' })).toBeHidden();
  expect(sent.writeAccess).toBe(1);
  expect(sent.settings).toHaveLength(1);
  expect(sent.settings[0]?.groups.find((row) => row.group === 'goods_launch')).toEqual({
    group: 'goods_launch',
    telegram: true,
    in_app: true,
  });
  // «Переезжаете?» — обычный мастер заявки S20a (шаблона «Уезжаю» нет, Q23)
  await page.getByRole('link', { name: /Переезжаете\?/ }).click();
  await expect(page.getByRole('heading', { name: 'Что нужно сделать?' })).toBeVisible();
  expect(real(watch.problems)).toEqual([]);
  expect(watch.unexpectedApi).toEqual([]);
});

test('S03 без флага goods.segment: сегмента «Услуги / Вещи» нет (бета, Q26)', async ({ page }) => {
  const watch = await open(page, 'theme=light&lang=ru', {
    config: { ...CLIENT_CONFIG, flags: { ...CLIENT_CONFIG.flags, 'goods.segment': false } },
  });

  await expect(page.getByRole('heading', { name: 'Найдём мастера рядом' })).toBeVisible();
  await expect(page.getByRole('radiogroup', { name: 'Раздел' })).toHaveCount(0);
  await expect(page.getByRole('radio', { name: 'Вещи' })).toHaveCount(0);
  expect(real(watch.problems)).toEqual([]);
});

test('S43: переключатель «Запуск раздела «Вещи»» снимает подписку', async ({ page }) => {
  const sent = sentRequests();
  const watch = await open(page, 'theme=light&lang=ru', {
    signedIn: true,
    notificationSettings: SUBSCRIBED,
    sent,
  });
  await openProfile(page);
  await page.getByRole('link', { name: 'Настройки', exact: true }).click();
  const launch = page.getByRole('switch', { name: 'Запуск раздела «Вещи»' });
  await expect(launch).toHaveAttribute('aria-checked', 'true');

  await launch.click();

  await expect(launch).toHaveAttribute('aria-checked', 'false');
  await expect.poll(() => sent.settings.length).toBe(1);
  expect(sent.settings[0]?.groups.find((row) => row.group === 'goods_launch')).toEqual({
    group: 'goods_launch',
    telegram: false,
    in_app: false,
  });
  expect(real(watch.problems)).toEqual([]);
  expect(watch.unexpectedApi).toEqual([]);
});
