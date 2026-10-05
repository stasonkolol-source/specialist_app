// S48 правовые документы и S49 системные состояния (DEVELOPMENT_PLAN 1.5a): скриншоты × тема × язык,
// axe-core и то, как приложение попадает в каждое состояние. Имена скриншотов начинаются с кода
// артборда: make design-compare кладёт их рядом с эталоном. Состояния S49 без своего артборда
// (техработы, «обновите Telegram», нет сети при старте) — в группе S49a: тот же вид «пустого
// состояния» на весь экран.
import type { Page } from '@playwright/test';
import { expect, test } from '@playwright/test';

import { CLIENT_CONFIG, ME } from '../src/testing/fixtures.ts';
import { json, problem } from './api.ts';
import {
  THEMES,
  expectNoAxeViolations,
  open,
  openProfile,
  openTab,
  pressTelegram,
  real,
} from './support.ts';

const LOCALES = [
  {
    locale: 'ru',
    telegram: 'ru',
    profile: 'Профиль',
    home: 'Главная',
    homeTitle: 'Найдём мастера рядом',
    rules: 'Правила площадки',
    edition: 'Редакция от 27 сентября 2026',
    privacyTab: 'Конфиденциальность',
    privacy: 'Политика конфиденциальности',
    offline: 'Нет соединения',
    offlineText: 'Проверьте интернет и попробуйте ещё раз',
    saved: 'Сохранено в 18:07',
    retry: 'Повторить',
    settings: 'Настройки',
    otherLanguage: 'Srpski (latinica)',
    restricted: 'Аккаунт ограничен до 3 октября',
    banner: 'До 3 октября, 18:00 нельзя откликаться на заявки',
    reason: 'Просьбы о предоплате — частая уловка мошенников',
    appealSent: 'Апелляция отправлена. Модератор ответит до 5 октября, 18:07 — ответ придёт в бот.',
    suspended: 'Аккаунт приостановлен до 3 октября',
    suspendedBanner: 'До 3 октября, 18:00 нельзя пользоваться аккаунтом',
    support: 'Написать в поддержку',
    left: 'Остаётся доступно',
    maintenance: 'Технические работы',
    updateTelegram: 'Обновите Telegram',
  },
  {
    locale: 'sr-Latn',
    telegram: 'sr',
    profile: 'Profil',
    home: 'Početna',
    homeTitle: 'Pronaći ćemo majstora u blizini',
    rules: 'Pravila platforme',
    // после «od» месяц — в родительном падеже (Intl даёт именительный, склоняет format.ts)
    // \s, а не пробел: типограф ставит неразрывный пробел после «od»
    edition: /^Verzija\sod\s27\.\sseptembra\s2026\.?$/,
    privacyTab: 'Privatnost',
    privacy: 'Politika privatnosti',
    offline: 'Nema veze',
    offlineText: 'Proverite internet i pokušajte ponovo',
    saved: 'Sačuvano u 18:07',
    retry: 'Pokušaj ponovo',
    settings: 'Podešavanja',
    otherLanguage: 'Русский',
    restricted: 'Nalog je ograničen do 3. oktobra',
    banner: 'Do 3. oktobra u 18:00 ne možete da šaljete ponude na zahteve',
    reason: 'Traženje avansa — česta prevara',
    appealSent:
      'Žalba je poslata. Moderator će odgovoriti do 5. oktobra u 18:07 — odgovor stiže u bot.',
    suspended: 'Nalog je suspendovan do 3. oktobra',
    suspendedBanner: 'Do 3. oktobra u 18:00 ne možete da koristite nalog',
    support: 'Piši podršci',
    left: 'I dalje je dostupno',
    maintenance: 'Tehnički radovi',
    updateTelegram: 'Ažurirajte Telegram',
  },
] as const;

/** Время демо-данных: «сейчас» для дат и «Сохранено в 18:07» (Нови-Сад, CEST). */
const NOW = new Date('2026-10-02T18:07:00+02:00');
/** Позже свежести /me (5 минут, app/query.ts): повторный заход на вкладку перечитывает профиль. */
const LATER = new Date('2026-10-02T18:13:00+02:00');
/** До 3 октября, 18:00 по Белграду — как на артборде S49b. */
const UNTIL = '2026-10-03T16:00:00Z';

/** Ответ POST /appeals: 72 часа с подачи (2 октября 18:07). */
const APPEAL = {
  id: '0192a000-0000-7000-8000-000000000001',
  appeal_of: '0192a000-0000-7000-8000-000000000002',
  status: 'pending',
  due_at: '2026-10-05T16:07:00Z',
  created_at: '2026-10-02T16:07:00Z',
  repeated: false,
};

/** Обрыв сети: браузер пишет в консоль ошибку загрузки — её вызывает сам сценарий. */
const OFFLINE_CONSOLE = 'ERR_INTERNET_DISCONNECTED';

/** Пропала сеть для GET /me: вернуть — `page.unroute`. */
const dropMe = (page: Page) =>
  page.route('**/api/v1/me', (route) => route.abort('internetdisconnected'));

for (const theme of THEMES) {
  for (const l of LOCALES) {
    test(`S48 правила ${theme} ${l.locale}: из профиля, версия из client-config`, async ({
      page,
    }) => {
      const watch = await open(page, `theme=${theme}&lang=${l.telegram}`);
      await openProfile(page, l.profile);

      await page.getByRole('link', { name: l.rules }).click();

      await expect(page.getByRole('heading', { name: l.rules, level: 1 })).toBeVisible();
      await expect(page.getByText(l.edition)).toBeVisible();
      // таббар — только на корневых экранах вкладок, у S48 «Назад» Telegram
      await expect(page.getByRole('navigation', { name: /Разделы|Odeljci/ })).toBeHidden();
      await expect(page.getByRole('heading', { name: 'Кто может пользоваться' })).toBeVisible();
      expect(real(watch.problems)).toEqual([]);
      expect(watch.unexpectedApi).toEqual([]);
      // первый экран документа — как артборд 390×844; весь текст проверяют unit-тесты
      await expect(page).toHaveScreenshot(`S48-rules-${theme}-${l.locale}.png`);
      await expectNoAxeViolations(page);

      await page.getByRole('radio', { name: l.privacyTab }).click();
      await expect(page.getByRole('heading', { name: l.privacy, level: 1 })).toBeVisible();
      await expect(page.getByRole('radio', { name: l.privacyTab })).toHaveAttribute(
        'aria-checked',
        'true',
      );
    });

    test(`S49a нет сети ${theme} ${l.locale}: сохранённый профиль приглушён, «Повторить»`, async ({
      page,
    }) => {
      await page.clock.setFixedTime(NOW);
      const watch = await open(page, `theme=${theme}&lang=${l.telegram}`, {
        signedIn: true,
        me: { ...ME, ui_locale: l.locale },
      });
      await openProfile(page, l.profile);
      await expect(page.getByRole('heading', { name: ME.display_name })).toBeVisible();

      // сеть пропала, профиль устарел: повторный заход на вкладку перечитывает /me и не может
      await dropMe(page);
      await page.clock.setFixedTime(LATER);
      await openTab(page, l.home);
      await openTab(page, l.profile);

      await expect(page.getByRole('heading', { name: l.offline })).toBeVisible({ timeout: 10_000 });
      await expect(page.getByText(l.saved)).toBeVisible();
      await expect(page.getByRole('heading', { name: ME.display_name })).toBeVisible();
      expect(real(watch.problems, [OFFLINE_CONSOLE])).toEqual([]);
      expect(watch.unexpectedApi).toEqual([]);
      await expect(page).toHaveScreenshot(`S49a-offline-${theme}-${l.locale}.png`, {
        fullPage: true,
      });
      // сохранённое приглушено по макету (opacity .55): там не проверяем только контраст
      await expectNoAxeViolations(page, { exclude: ['[data-stale]'] });
      await expectNoAxeViolations(page, { include: '[data-stale]', disable: ['color-contrast'] });

      await page.unroute('**/api/v1/me');
      await page.getByRole('button', { name: l.retry }).click();
      await expect(page.getByRole('heading', { name: l.offline })).toBeHidden();
      await expect(page.getByText(l.saved)).toBeHidden();
    });

    test(`S49b ограничен ${theme} ${l.locale}: санкция с причиной, «Обжаловать»`, async ({
      page,
    }) => {
      await page.clock.setFixedTime(NOW);
      const appeals: unknown[] = [];
      // 403 restricted на мутацию; сейчас единственная — смена языка, с шагов 5.x — отклик
      const watch = await open(page, `theme=${theme}&lang=${l.telegram}`, {
        signedIn: true,
        me: { ...ME, ui_locale: l.locale },
        handlers: {
          'PATCH /api/v1/me': (route) =>
            route.fulfill(
              problem(403, 'restricted', {
                restriction: 'responding_blocked',
                until: UNTIL,
                reason: 'prepayment_scam',
              }),
            ),
          'POST /api/v1/appeals': (route) => {
            appeals.push(route.request().postDataJSON());
            return route.fulfill(json(APPEAL, 201));
          },
        },
      });
      await openProfile(page, l.profile);
      await expect(page.getByRole('heading', { name: ME.display_name })).toBeVisible();
      // язык — в настройках S43 (4.9)
      await page.getByRole('link', { name: l.settings, exact: true }).click();

      await page.getByRole('radio', { name: l.otherLanguage }).click();

      await expect(page.getByRole('heading', { name: l.restricted, level: 1 })).toBeVisible();
      await expect(page.getByRole('alert')).toHaveText(l.banner);
      await expect(page.getByText(l.reason)).toBeVisible();
      // «Обжаловать» — MainButton: нативная, в DOM mock-клиента её нет (видимость — unit-тесты)
      await expect(page.getByRole('navigation', { name: /Разделы|Odeljci/ })).toBeHidden();
      expect(real(watch.problems, ['403'])).toEqual([]);
      expect(watch.unexpectedApi).toEqual([]);
      await expect(page).toHaveScreenshot(`S49b-restricted-${theme}-${l.locale}.png`, {
        fullPage: true,
      });
      await expectNoAxeViolations(page);

      await pressTelegram(page, 'main_button_pressed');

      await expect(page.getByRole('status')).toHaveText(l.appealSent);
      expect(appeals).toEqual([{ restriction: 'responding_blocked' }]);
      await expect(page).toHaveScreenshot(`S49b-appealed-${theme}-${l.locale}.png`, {
        fullPage: true,
      });
      await expectNoAxeViolations(page);

      await page.getByRole('button', { name: l.rules }).click();
      await expect(page.getByRole('heading', { name: l.rules, level: 1 })).toBeVisible();
    });
  }
}

// Экраны S49 при старте — без оболочки маршрутов, но в теме и на языке пользователя
for (const theme of THEMES) {
  for (const l of LOCALES) {
    const query = `theme=${theme}&lang=${l.telegram}`;

    test(`S49b санкция на весь аккаунт ${theme} ${l.locale}: вход отклонён, приложение закрыто`, async ({
      page,
    }) => {
      await page.clock.setFixedTime(NOW);
      const watch = await open(page, query, {
        // контакт поддержки задан (Q25): кнопки «Обжаловать» нет, путь — строка поддержки
        config: { ...CLIENT_CONFIG, support_username: 'sosedi_support' },
        handlers: {
          'POST /api/v1/auth/telegram': (route) =>
            route.fulfill(problem(403, 'restricted', { restriction: 'suspended', until: UNTIL })),
        },
      });

      await expect(page.getByRole('heading', { name: l.suspended, level: 1 })).toBeVisible();
      await expect(page.getByRole('alert')).toHaveText(l.suspendedBanner);
      await expect(page.getByRole('button', { name: l.support })).toBeVisible();
      // весь аккаунт закрыт: списка «Остаётся доступно» и таббара нет
      await expect(page.getByText(l.left)).toHaveCount(0);
      await expect(page.getByRole('navigation', { name: /Разделы|Odeljci/ })).toHaveCount(0);
      expect(real(watch.problems, ['403'])).toEqual([]);
      await expect(page).toHaveScreenshot(`S49b-suspended-${theme}-${l.locale}.png`, {
        fullPage: true,
      });
      await expectNoAxeViolations(page);

      await page.getByRole('button', { name: l.rules }).click();
      await expect(page.getByRole('heading', { name: l.rules, level: 1 })).toBeVisible();
    });

    test(`S49a нет сети при старте ${theme} ${l.locale}: «Повторить» открывает приложение`, async ({
      page,
    }) => {
      let online = false;
      const watch = await open(page, query, {
        handlers: {
          'GET /api/v1/client-config': (route) =>
            online ? route.fulfill(json(CLIENT_CONFIG)) : route.abort('internetdisconnected'),
        },
      });

      await expect(page.getByRole('heading', { name: l.offline, level: 1 })).toBeVisible({
        timeout: 10_000,
      });
      await expect(page.getByText(l.offlineText)).toBeVisible();
      expect(real(watch.problems, [OFFLINE_CONSOLE])).toEqual([]);
      await expect(page).toHaveScreenshot(`S49a-start-offline-${theme}-${l.locale}.png`, {
        fullPage: true,
      });
      await expectNoAxeViolations(page);

      online = true;
      await page.getByRole('button', { name: l.retry }).click();
      await expect(page.getByRole('heading', { name: l.homeTitle, level: 1 })).toBeVisible();
    });

    test(`S49 техработы ${theme} ${l.locale}: флаг client-config закрывает приложение`, async ({
      page,
    }) => {
      const watch = await open(page, query, {
        config: {
          ...CLIENT_CONFIG,
          flags: { ...CLIENT_CONFIG.flags, 'platform.maintenance': true },
        },
      });

      await expect(page.getByRole('heading', { name: l.maintenance, level: 1 })).toBeVisible();
      await expect(page.getByRole('button', { name: l.retry })).toBeVisible();
      expect(real(watch.problems)).toEqual([]);
      await expect(page).toHaveScreenshot(`S49a-maintenance-${theme}-${l.locale}.png`, {
        fullPage: true,
      });
      await expectNoAxeViolations(page);
    });

    test(`S49 «обновите Telegram» ${theme} ${l.locale}: Bot API клиента ниже минимума`, async ({
      page,
    }) => {
      const watch = await open(page, `${query}&tg=6.0`);

      await expect(page.getByRole('heading', { name: l.updateTelegram, level: 1 })).toBeVisible();
      // повторять нечего: помогает только обновление клиента
      await expect(page.getByRole('button')).toHaveCount(0);
      expect(real(watch.problems)).toEqual([]);
      await expect(page).toHaveScreenshot(`S49a-update-telegram-${theme}-${l.locale}.png`, {
        fullPage: true,
      });
      await expectNoAxeViolations(page);
    });
  }
}

test('S49 техработы: 503 maintenance от API', async ({ page }) => {
  const watch = await open(page, 'theme=dark&lang=sr', {
    handlers: {
      'POST /api/v1/auth/telegram': (route) => route.fulfill(problem(503, 'maintenance')),
    },
  });

  await expect(page.getByRole('heading', { name: 'Tehnički radovi', level: 1 })).toBeVisible();
  expect(real(watch.problems, ['503'])).toEqual([]);
  await expectNoAxeViolations(page);
});

test('S49 426 от API: новая версия Mini App — «Перезагрузить»', async ({ page }) => {
  const watch = await open(page, 'theme=light&lang=ru', {
    handlers: {
      'POST /api/v1/auth/telegram': (route) =>
        route.fulfill(
          problem(426, 'client_upgrade_required', { platform: 'tma', min_version: '9.0.0' }),
        ),
    },
  });

  await expect(page.getByRole('heading', { name: 'Вышла новая версия', level: 1 })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Перезагрузить' })).toBeVisible();
  expect(real(watch.problems, ['426'])).toEqual([]);
  await expectNoAxeViolations(page);
});

test('S49a нет сети: чанк вкладки не скачался — «Нет соединения», а не перезагрузка', async ({
  page,
  context,
}) => {
  // чанк «Сообщений» недоступен с самого старта: фоновая загрузка вкладок его не получила
  await page.route('**/assets/s29-chats-*.js', (route) => route.abort('internetdisconnected'));
  const watch = await open(page, 'theme=light&lang=ru');
  await expect(page.getByRole('heading', { name: 'Найдём мастера рядом', level: 1 })).toBeVisible();
  // метка в памяти страницы: перезагрузка её сотрёт (sessionStorage пережил бы)
  await page.evaluate(() => Object.assign(window, { e2eSamePage: true }));

  // сеть пропала (метро), вкладка открывается впервые
  await context.setOffline(true);
  await openTab(page, 'Сообщения');

  await expect(page.getByRole('heading', { name: 'Нет соединения', level: 1 })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Повторить' })).toBeVisible();
  // та же страница: без сети Mini App не перезагружался, запасного экрана роутера нет
  expect(await page.evaluate(() => 'e2eSamePage' in window)).toBe(true);
  await expect(page.getByText(/Something went wrong/)).toHaveCount(0);
  expect(
    real(watch.problems, [
      OFFLINE_CONSOLE,
      // так WebKit пишет об оборванной загрузке скрипта модуля
      'WebKit encountered an internal error',
      'screen chunk failed',
      'dynamically imported module',
      'Importing a module script failed',
    ]),
  ).toEqual([]);
});

test('S03 нет сети: блок Главной не скачался — Главная работает без него', async ({ page }) => {
  // «Ищете подработку?» — своим чанком после первого кадра: сеть пропала раньше, чем он скачался
  await page.route('**/assets/SideJob-*.js', (route) => route.abort('internetdisconnected'));
  const watch = await open(page, 'theme=light&lang=ru');

  await expect(page.getByRole('heading', { name: 'Найдём мастера рядом', level: 1 })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Свободны сегодня рядом' })).toBeVisible();
  await expect(page.getByText('Ищете подработку?')).toHaveCount(0);
  await expect(page.getByRole('heading', { name: 'Нет соединения' })).toHaveCount(0);
  await openTab(page, 'Заявки');
  await expect(page.getByRole('heading', { name: 'Заявки рядом', level: 1 })).toBeVisible();
  expect(
    real(watch.problems, [
      OFFLINE_CONSOLE,
      'WebKit encountered an internal error',
      'dynamically imported module',
      'Importing a module script failed',
    ]),
  ).toEqual([]);
});
