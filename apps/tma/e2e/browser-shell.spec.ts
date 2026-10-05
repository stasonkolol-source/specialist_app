// Браузерная оболочка (DEVELOPMENT_PLAN 8.1): тот же SPA без Telegram (platform=browser) — без
// `?platform=mock`. Веб-ссылка `/s/<id>` → «Открыть в Telegram» (t.me бота с кодом startapp) или
// «Продолжить в браузере» → S08 гостем со своей шапкой «Назад» и одной кнопкой — «Написать в
// Telegram» сразу на этот профиль; `/j/<id>` → S15; экраны, которых в браузере нет, — «Открыть в
// Telegram»; «Как удалить аккаунт» без входа.
// Заголовки собранного приложения: frame-ancestors с web.telegram.org, без X-Frame-Options.
// Проекты — desktop и мобильный chromium; скриншоты × тема × язык (язык — из браузера), axe-core.
import { uuidToBase62 } from '@sosed/links';
import type { Page } from '@playwright/test';
import { expect, test } from '@playwright/test';

import { CARD_PROFILE_ID, E2E_NOW } from '../src/testing/fixtures.ts';
import { FEED_JOBS } from '../src/testing/jobsBackend.ts';
import { mockApi } from './api.ts';
import { THEMES, expectNoAxeViolations } from './support.ts';

/** Бот сборки e2e (`VITE_TELEGRAM_BOT` в e2e:build). */
const BOT = 'sosed_e2e_bot';
const NAME = 'Алексей Морозов';
const PROFILE = uuidToBase62(CARD_PROFILE_ID);
const JOB_ID = FEED_JOBS[1]?.card.id ?? '';

const LOCALES = [
  {
    locale: 'ru',
    browser: 'ru-RU',
    specialist: 'Профиль специалиста',
    app: '«Соседи» живут в Telegram',
    open: 'Открыть в Telegram',
    next: 'Продолжить в браузере',
    write: 'Написать в Telegram',
    propose: 'Предложить заявку',
    back: 'Назад',
    deletion: 'Как удалить аккаунт',
  },
  {
    locale: 'sr-Latn',
    browser: 'sr-RS',
    specialist: 'Profil stručnjaka',
    app: '„Sosedi“ su u Telegram-u',
    open: 'Otvori u Telegram-u',
    next: 'Nastavi u pregledaču',
    write: 'Napiši poruku u Telegram-u',
    propose: 'Predloži zahtev',
    back: 'Nazad',
    deletion: 'Kako obrisati nalog',
  },
] as const;

test.beforeEach(({ browserName }, info) => {
  test.skip(
    browserName !== 'chromium' || !['desktop', 'chromium-360'].includes(info.project.name),
    'desktop и мобильный chromium',
  );
});

/** Открыть адрес без Telegram: всё, чего быть не должно, — в `problems` и `unexpectedApi`. */
async function visit(page: Page, path: string) {
  const problems: string[] = [];
  const unexpectedApi: string[] = [];
  page.on('request', (request) => {
    if (!request.url().startsWith('http://127.0.0.1')) problems.push(`network ${request.url()}`);
  });
  page.on('console', (message) => {
    if (message.type() === 'error') problems.push(`console ${message.text()}`);
  });
  page.on('pageerror', (error) => problems.push(`page ${error.message}`));
  await mockApi(page, unexpectedApi);
  const response = await page.goto(path);
  await page.evaluate(() => document.fonts.ready);
  return { problems, unexpectedApi, response };
}

for (const theme of THEMES) {
  for (const l of LOCALES) {
    test.describe(() => {
      test.use({ locale: l.browser, colorScheme: theme });

      test(`browser-shell ${theme} ${l.locale}: /s/<id> → S08 гостем и «Назад»`, async ({
        page,
      }) => {
        await page.clock.setFixedTime(new Date(E2E_NOW));
        const watch = await visit(page, `/s/${PROFILE}`);
        const snap = async (name: string) => {
          expect(watch.problems).toEqual([]);
          expect(watch.unexpectedApi).toEqual([]);
          await expect(page).toHaveScreenshot(name, { fullPage: true });
          await expectNoAxeViolations(page);
        };

        await expect(page.getByRole('heading', { name: l.specialist, level: 1 })).toBeVisible();
        await expect(page.locator('html')).toHaveAttribute('data-theme', theme);
        await expect(page.getByRole('link', { name: l.open })).toHaveAttribute(
          'href',
          `https://t.me/${BOT}?startapp=s_${PROFILE}`,
        );
        await expect(page.getByRole('button', { name: l.back })).toHaveCount(0);
        await snap(`browser-link-${theme}-${l.locale}.png`);

        await page.getByRole('button', { name: l.next }).click();
        await expect(page.getByRole('heading', { name: NAME, level: 1 })).toBeVisible();
        await expect(page).toHaveURL(`/specialists/${CARD_PROFILE_ID}`);
        // одна кнопка гостя — ссылка в Telegram сразу на этот профиль; таббара в браузере нет
        await expect(page.getByRole('link', { name: l.write })).toHaveAttribute(
          'href',
          `https://t.me/${BOT}?startapp=s_${PROFILE}`,
        );
        await expect(page.getByRole('button', { name: l.propose })).toHaveCount(0);
        await expect(page.getByRole('navigation')).toHaveCount(0);
        await snap(`browser-S08-${theme}-${l.locale}.png`);

        await page.getByRole('button', { name: l.back }).click();
        await expect(page.getByRole('heading', { name: l.specialist, level: 1 })).toBeVisible();
      });

      test(`browser-shell ${theme} ${l.locale}: «Как удалить аккаунт»`, async ({ page }) => {
        const watch = await visit(page, '/delete-account');

        await expect(page.getByRole('heading', { name: l.deletion, level: 1 })).toBeVisible();
        await expect(page.locator('a[href$="startapp=m_deletion"]')).toBeVisible();
        expect(watch.problems).toEqual([]);
        expect(watch.unexpectedApi).toEqual([]);
        await expect(page).toHaveScreenshot(`browser-deletion-${theme}-${l.locale}.png`, {
          fullPage: true,
        });
        await expectNoAxeViolations(page);
      });
    });
  }
}

test('browser-shell: /j/<id> → S15 гостем; экраны вне браузера — «Открыть в Telegram»', async ({
  page,
}) => {
  await page.clock.setFixedTime(new Date(E2E_NOW));
  const job = uuidToBase62(JOB_ID);
  const watch = await visit(page, `/j/${job}`);
  const ru = LOCALES[0];

  await expect(page.getByRole('heading', { name: 'Заявка', level: 1 })).toBeVisible();
  await expect(page.getByRole('link', { name: ru.open })).toHaveAttribute(
    'href',
    `https://t.me/${BOT}?startapp=j_${job}`,
  );
  await page.getByRole('button', { name: ru.next }).click();
  await expect(page.getByRole('heading', { name: 'Повесить люстру', level: 1 })).toBeVisible();

  // «Откликнуться» гостем — формы отклика в браузере нет: Telegram на той же заявке
  await page.getByRole('button', { name: /Откликнуться/ }).click();
  await expect(page.getByRole('heading', { name: ru.app, level: 1 })).toBeVisible();
  await expect(page.getByRole('link', { name: ru.open })).toHaveAttribute(
    'href',
    `https://t.me/${BOT}?startapp=j_${job}`,
  );
  await expect(page.getByRole('button', { name: ru.next })).toHaveCount(0);
  await page.getByRole('button', { name: ru.back }).click();
  await expect(page.getByRole('heading', { name: 'Повесить люстру', level: 1 })).toBeVisible();

  // главная — тоже Telegram; ссылка «Как удалить аккаунт» есть и здесь
  await page.goto('/');
  await expect(page.getByRole('heading', { name: ru.app, level: 1 })).toBeVisible();
  await expect(page.getByRole('link', { name: ru.open })).toHaveAttribute(
    'href',
    `https://t.me/${BOT}?startapp=h`,
  );
  await page.getByRole('link', { name: ru.deletion }).click();
  await expect(page.getByRole('heading', { name: ru.deletion, level: 1 })).toBeVisible();
  expect(watch.problems).toEqual([]);
  expect(watch.unexpectedApi).toEqual([]);
});

test('browser-shell: Telegram Web может открыть приложение во фрейме', async ({ page }) => {
  const { response } = await visit(page, `/s/${PROFILE}`);
  const headers = response?.headers() ?? {};
  expect(headers['content-security-policy']).toContain('frame-ancestors https://web.telegram.org');
  expect(headers['x-frame-options']).toBeUndefined();
});
