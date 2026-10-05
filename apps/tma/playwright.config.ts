// e2e Mini App (DEVELOPMENT_PLAN 0.21b): собранное приложение на mock-платформе (mockTelegramEnv),
// API — фикстуры SPEC §4. Запуск только в Docker-образе Playwright (make e2e PKG=tma): шрифты и
// рендер одинаковы локально и в CI. Обновить эталоны: make e2e PKG=tma UPDATE=1.
import { defineConfig, devices } from '@playwright/test';

const PORT = 4174;
const mobile = { deviceScaleFactor: 1, isMobile: true, hasTouch: true };

export default defineConfig({
  testDir: 'e2e',
  snapshotPathTemplate: '{testDir}/__screenshots__/{arg}-{projectName}{ext}',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: 0,
  reporter: [['list'], ['html', { open: 'never', outputFolder: 'playwright-report' }]],
  expect: { toHaveScreenshot: { maxDiffPixelRatio: 0.002, animations: 'disabled' } },
  // «Уменьшить движение»: шторка и тост появляются сразу, без въезда. Иначе на медленном раннере CI
  // тест нажимал в шторке, пока она ещё ехала, фокус прокручивал её, и снимок S14 съезжал (#198)
  use: { baseURL: `http://127.0.0.1:${PORT}`, reducedMotion: 'reduce' },
  projects: [
    // iPhone 12–15: основной телефон аудитории, WebKit как в Telegram iOS
    {
      name: 'webkit-390',
      use: { ...devices['iPhone 13'], viewport: { width: 390, height: 844 }, ...mobile },
    },
    // Android: узкий экран и старый маленький iPhone-формат
    {
      name: 'chromium-360',
      use: { ...devices['Pixel 7'], viewport: { width: 360, height: 800 }, ...mobile },
    },
    {
      name: 'chromium-375',
      use: { ...devices['Pixel 7'], viewport: { width: 375, height: 667 }, ...mobile },
    },
    // Telegram Desktop и Web: колонка max-w по центру
    {
      name: 'desktop',
      use: {
        ...devices['Desktop Chrome'],
        viewport: { width: 1280, height: 800 },
        deviceScaleFactor: 1,
      },
    },
  ],
  webServer: {
    command: `node scripts/serve.mjs dist ${PORT}`,
    url: `http://127.0.0.1:${PORT}`,
    reuseExistingServer: false,
  },
});
