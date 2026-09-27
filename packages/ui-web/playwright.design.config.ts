// Рендер PNG-эталонов артбордов (make design-render → pnpm design:render). Только в Docker-образе Playwright.
import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: 'design-refs',
  fullyParallel: true,
  retries: 0,
  reporter: [['list']],
  outputDir: 'test-results/design-refs',
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'], deviceScaleFactor: 1 } }],
});
