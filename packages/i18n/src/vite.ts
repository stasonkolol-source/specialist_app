// Vite-плагин: типограф (typograph.ts) над каталогами ru и sr-Cyrl при загрузке JSON — в dev и в
// сборке; sr-Latn — транслитерация sr-Cyrl в рантайме и неразрывные пробелы наследует. В Vitest
// плагина нет: Testing Library сравнивает имя роли без нормализации пробелов, и `getByRole('button',
// { name: 'Не подходит' })` не нашёл бы кнопку с неразрывным пробелом. Playwright строки и имена
// нормализует, а регулярки проверяет по сырому тексту — в e2e пробел в них пишем как `\s`.
// Тип плагина — структурно: пакету не нужна зависимость от vite.
import type { TypographLocale } from './typograph.ts';
import { typographCatalog } from './typograph.ts';

const CATALOG = /\/catalogs\/(ru|sr-Cyrl)\/[\w-]+\.json$/;

export function typograph() {
  return {
    name: 'sosed-i18n-typograph',
    enforce: 'pre' as const,
    transform(code: string, id: string) {
      const locale = CATALOG.exec(id.split('?', 1)[0] ?? id)?.[1] as TypographLocale | undefined;
      if (locale === undefined) return null;
      return { code: JSON.stringify(typographCatalog(JSON.parse(code), locale)), map: null };
    },
  };
}
