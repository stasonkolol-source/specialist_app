// S44 Заблокированные и S46 Жалоба (DEVELOPMENT_PLAN 4.7): скриншоты × тема × язык и axe-core.
// S44 — из настроек S43 (строка с числом): двое заблокированных, как на артборде. S46 — шторка на
// карточке S08 вошедшего: причина «Мошенничество…», подробности и «Также заблокировать», как на
// артборде; отправка — «Жалоба отправлена», на S08 — «Разблокировать». Меню «⋯» чата S30: попап
// Telegram отвечает по очереди из `?popup=` — жалоба на собеседника и блокировка. Имена скриншотов
// начинаются с кода артборда: make design-compare кладёт их рядом с эталоном.
import { encodeStartParam } from '@sosed/links';
import { expect, test } from '@playwright/test';

import { ChatBackend } from '../src/testing/chatBackend.ts';
import { CARD_PROFILE_ID, E2E_NOW, ME } from '../src/testing/fixtures.ts';
import { ARTBOARD_BLOCKS, SafetyBackend } from '../src/testing/safetyBackend.ts';
import { THEMES, expectNoAxeViolations, open, openProfile, openTab, real } from './support.ts';

const LOCALES = [
  {
    locale: 'ru',
    telegram: 'ru',
    profile: 'Профиль',
    settings: 'Настройки',
    blockedRow: /^Заблокированные/,
    blocked: 'Заблокированные',
    list: 'Заблокированные пользователи',
    reportRow: 'Пожаловаться на профиль',
    sheet: 'Пожаловаться на профиль',
    fraud: 'Мошенничество или просит предоплату',
    details: 'Подробности',
    comment: 'Попросил перевести 2 000 RSD на карту до приезда',
    alsoBlock: 'Также заблокировать специалиста',
    send: 'Отправить жалобу',
  },
  {
    locale: 'sr-Latn',
    telegram: 'sr',
    profile: 'Profil',
    settings: 'Podešavanja',
    blockedRow: /^Blokirani/,
    blocked: 'Blokirani',
    list: 'Blokirani korisnici',
    reportRow: 'Prijavi profil',
    sheet: 'Prijavi profil',
    fraud: 'Prevara ili traži avans',
    details: 'Detalji',
    comment: 'Tražio je da mu prebacim 2 000 RSD na karticu pre dolaska',
    alsoBlock: 'Blokiraj i stručnjaka',
    send: 'Pošalji prijavu',
  },
] as const;

const PROFILE_START = encodeStartParam({ type: 'specialist', id: CARD_PROFILE_ID });

for (const theme of THEMES) {
  for (const l of LOCALES) {
    test(`S44 ${theme} ${l.locale}: заблокированные из настроек`, async ({ page }) => {
      await page.clock.setFixedTime(new Date(E2E_NOW));
      const watch = await open(page, `theme=${theme}&lang=${l.telegram}`, {
        signedIn: true,
        me: { ...ME, ui_locale: l.locale },
        safety: new SafetyBackend(ARTBOARD_BLOCKS),
      });
      await openProfile(page, l.profile);
      await page.getByRole('link', { name: l.settings, exact: true }).click();
      const row = page.getByRole('link', { name: l.blockedRow });
      await expect(row).toContainText('2');
      await row.click();

      await expect(page.getByRole('heading', { name: l.blocked, level: 1 })).toBeVisible();
      await expect(page.getByRole('list', { name: l.list }).getByRole('listitem')).toHaveCount(2);
      expect(real(watch.problems)).toEqual([]);
      expect(watch.unexpectedApi).toEqual([]);
      await expect(page).toHaveScreenshot(`S44-blocked-${theme}-${l.locale}.png`, {
        fullPage: true,
      });
      await expectNoAxeViolations(page);
    });

    test(`S46 ${theme} ${l.locale}: жалоба на профиль`, async ({ page }) => {
      await page.clock.setFixedTime(new Date(E2E_NOW));
      const watch = await open(page, `theme=${theme}&lang=${l.telegram}&start=${PROFILE_START}`, {
        signedIn: true,
        me: { ...ME, ui_locale: l.locale },
      });
      await page.getByRole('main').getByRole('button', { name: l.reportRow }).click();

      const sheet = page.getByRole('dialog', { name: l.sheet });
      await sheet.getByRole('radio', { name: l.fraud }).click();
      await sheet.getByLabel(l.details).fill(l.comment);
      await sheet.getByRole('checkbox', { name: l.alsoBlock }).click();
      await expect(sheet.getByRole('checkbox', { name: l.alsoBlock })).toHaveAttribute(
        'aria-checked',
        'true',
      );
      // фокус уходит из поля: каретка мигала бы на снимке
      await sheet.getByRole('radio', { name: l.fraud }).focus();
      expect(real(watch.problems)).toEqual([]);
      expect(watch.unexpectedApi).toEqual([]);
      // шторка закреплена на экране: снимок экрана, как артборд 390×844, а не всей страницы
      await expect(page).toHaveScreenshot(`S46-report-${theme}-${l.locale}.png`);
      await expectNoAxeViolations(page, { include: '[role="dialog"]' });
    });
  }
}

test('S46: жалоба уходит, специалист заблокирован, на S08 — «Разблокировать»', async ({ page }) => {
  await page.clock.setFixedTime(new Date(E2E_NOW));
  const safety = new SafetyBackend();
  const watch = await open(page, `theme=light&lang=ru&start=${PROFILE_START}`, {
    signedIn: true,
    safety,
  });
  await page.getByRole('main').getByRole('button', { name: 'Пожаловаться на профиль' }).click();
  const sheet = page.getByRole('dialog', { name: 'Пожаловаться на профиль' });
  await sheet.getByRole('radio', { name: 'Запрещённые услуги' }).click();
  await sheet.getByRole('checkbox', { name: 'Также заблокировать специалиста' }).click();
  await sheet.getByRole('button', { name: 'Отправить жалобу' }).click();

  const done = page.getByRole('dialog', { name: 'Жалоба отправлена' });
  await expect(
    done.getByText('Модератор проверит её в течение часа, с 08:00 до 23:00.'),
  ).toBeVisible();
  await done.getByRole('button', { name: 'Готово' }).click();
  await expect(page.getByRole('dialog')).toBeHidden();
  await expect(page.getByRole('button', { name: 'Разблокировать' })).toBeVisible();
  expect(safety.reports.map((report) => [report.target_type, report.reason])).toEqual([
    ['profile', 'prohibited'],
  ]);
  expect(real(watch.problems)).toEqual([]);
  expect(watch.unexpectedApi).toEqual([]);
});

test('S30: «⋯» — жалоба на собеседника и блокировка закрывают переписку', async ({ page }) => {
  await page.clock.setFixedTime(new Date(E2E_NOW));
  const safety = new SafetyBackend();
  const watch = await open(page, 'theme=light&lang=ru&popup=report,block,ok', {
    signedIn: true,
    chat: new ChatBackend().seed(),
    safety,
  });
  await openTab(page, 'Сообщения');
  await page.getByRole('link', { name: /Алексей Морозов/ }).click();
  const menu = page.getByRole('button', { name: 'Меню диалога: пожаловаться или заблокировать' });

  await menu.click();
  const sheet = page.getByRole('dialog', { name: 'Пожаловаться на собеседника' });
  await sheet.getByRole('radio', { name: 'Мошенничество или просит предоплату' }).click();
  await sheet.getByRole('button', { name: 'Отправить жалобу' }).click();
  await page
    .getByRole('dialog', { name: 'Жалоба отправлена' })
    .getByRole('button', { name: 'Готово' })
    .click();
  await expect(page.getByRole('dialog')).toBeHidden();
  expect(safety.reports[0]?.conversation_id).toBeTruthy();

  await menu.click(); // попап — «Заблокировать», затем подтверждение «ok»
  await expect(
    page.getByText('Вы заблокировали собеседника. Переписка — только для чтения.'),
  ).toBeVisible();
  await expect(page.getByRole('textbox', { name: 'Сообщение' })).toBeHidden();
  expect(real(watch.problems)).toEqual([]);
  expect(watch.unexpectedApi).toEqual([]);
});
