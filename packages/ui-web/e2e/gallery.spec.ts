// Скриншот каждого раздела галереи × тема × локаль. Обновить эталоны: make e2e PKG=ui-web UPDATE=1.
import { expect, test } from '@playwright/test';

export const SECTIONS = ['typography', 'buttons', 'badges', 'avatars', 'cards', 'icons', 'tabbar'];
const THEMES = ['light', 'dark'];
const LOCALES = ['ru', 'sr-Latn', 'sr-Cyrl'];

for (const theme of THEMES) {
  for (const lang of LOCALES) {
    test(`галерея ${theme} ${lang}`, async ({ page }) => {
      const external: string[] = [];
      page.on('request', (r) => {
        if (!r.url().startsWith('http://127.0.0.1')) external.push(r.url());
      });
      await page.goto(`/?theme=${theme}&lang=${lang}`);
      await page.evaluate(() => document.fonts.ready);
      // шрифты self-host: Google Fonts и прочая сеть не нужны
      expect(external).toEqual([]);
      expect(await page.evaluate(() => document.fonts.check('600 16px Onest'))).toBe(true);
      for (const section of SECTIONS) {
        await expect(page.locator(`[data-gallery="${section}"]`)).toHaveScreenshot(
          `${section}-${theme}-${lang}.png`,
        );
      }
    });
  }
}
