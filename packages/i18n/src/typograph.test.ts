import { readFileSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

import type { Catalog } from './catalog.ts';
import { flattenCatalog, messageArguments } from './catalog.ts';
import { typographCatalog, typographMessage } from './typograph.ts';
import { typograph } from './vite.ts';

const NBSP = String.fromCharCode(0xa0);
/** «~» в ожидаемой строке — неразрывный пробел. */
const nb = (text: string) => text.replaceAll('~', NBSP);
const ru = (text: string) => typographMessage(text, 'ru');

describe('typographMessage', () => {
  it('glues the space before a dash: a line never starts with «—»', () => {
    expect(ru('Платите после работы — так безопаснее')).toBe(
      nb('Платите после работы~— так безопаснее'),
    );
    expect(ru('{place} — точный адрес')).toBe(nb('{place}~— точный адрес'));
  });

  it('glues short prepositions, conjunctions and one-letter words to the next word', () => {
    expect(ru('Мастер на час')).toBe(nb('Мастер на~час'));
    expect(ru('В шаблоне — сообщение')).toBe(nb('В~шаблоне~— сообщение'));
    expect(ru('а я принимаю правила')).toBe(nb('а~я~принимаю правила'));
    expect(ru('Профили не публикуются')).toBe(nb('Профили не~публикуются'));
    expect(ru('из-за дождя')).toBe(nb('из-за~дождя'));
  });

  it('leaves words that only end like a short word and short words at the end', () => {
    expect(ru('Нови-Сад и Белград')).toBe(nb('Нови-Сад и~Белград'));
    expect(ru('Сделка завершена на')).toBe('Сделка завершена на');
    expect(ru('сова летит')).toBe('сова летит');
  });

  it('glues a number to the next word', () => {
    expect(ru('откликнутся до 5 исполнителей')).toBe(nb('откликнутся до~5~исполнителей'));
    expect(ru('Мне есть 18 лет')).toBe(nb('Мне есть 18~лет'));
    expect(ru('2 000–4 000 RSD')).toBe(nb('2 000–4 000~RSD'));
  });

  it('keeps ICU syntax and changes only text, including plural branches', () => {
    expect(ru('{count, plural, one {# заявка} other {# заявок}}, новые сверху')).toBe(
      nb('{count, plural, one {#~заявка} other {#~заявок}}, новые сверху'),
    );
    expect(ru('Шаг {current} из {total}. Черновик сохраняется сам')).toBe(
      nb('Шаг {current} из~{total}. Черновик сохраняется сам'),
    );
    expect(ru('{count, number} из {max, number}')).toBe(nb('{count, number}~из~{max, number}'));
    expect(ru('{kind, select, a {в доме} other {у нас}}')).toBe(
      nb('{kind, select, a {в~доме} other {у~нас}}'),
    );
    expect(ru('{a} и {b}')).toBe(nb('{a} и~{b}'));
    expect(ru('<b>в доме</b> и <link>ещё</link>')).toBe(nb('<b>в~доме</b> и~<link>ещё</link>'));
  });

  it('uses the Serbian list for sr-Cyrl', () => {
    expect(typographMessage('Мајстори у близини и на вашем језику', 'sr-Cyrl')).toBe(
      nb('Мајстори у~близини и~на~вашем језику'),
    );
    // «я» — русское слово, в сербском списке его нет
    expect(typographMessage('я тест', 'sr-Cyrl')).toBe('я тест');
  });
});

describe('typographCatalog', () => {
  it('keeps keys and nesting', () => {
    expect(typographCatalog({ a: 'в доме', b: { c: 'на час' } }, 'ru')).toEqual({
      a: nb('в~доме'),
      b: { c: nb('на~час') },
    });
  });

  // Охрана настоящих каталогов: типограф меняет только пробелы (неразрывные в каталогах уже есть —
  // «{count} мин») и не ломает ICU — те же аргументы.
  const dir = fileURLToPath(new URL('./catalogs/', import.meta.url));
  for (const locale of ['ru', 'sr-Cyrl'] as const) {
    it(`changes only spaces in every ${locale} message`, () => {
      for (const file of readdirSync(`${dir}${locale}`).filter((f) => f.endsWith('.json'))) {
        const source = JSON.parse(readFileSync(`${dir}${locale}/${file}`, 'utf8')) as Catalog;
        const typed = flattenCatalog(typographCatalog(source, locale));
        for (const [key, message] of Object.entries(flattenCatalog(source))) {
          const result = typed[key] ?? '';
          expect(result.replaceAll(NBSP, ' '), `${file}: ${key}`).toBe(
            message.replaceAll(NBSP, ' '),
          );
          expect(messageArguments(result, locale), `${file}: ${key}`).toEqual(
            messageArguments(message, locale),
          );
        }
      }
    });
  }

  it('fixes the Home S03 lines from the review', () => {
    const ruCatalog = (file: string) =>
      flattenCatalog(
        typographCatalog(
          JSON.parse(readFileSync(`${dir}ru/${file}.json`, 'utf8')) as Catalog,
          'ru',
        ),
      );
    expect(ruCatalog('common')['category.handyman']).toBe(nb('Мастер на~час'));
    expect(ruCatalog('catalog')['home.createText']).toContain(nb('до~5~исполнителей'));
  });
});

describe('vite plugin', () => {
  const plugin = typograph();

  it('typographs ru and sr-Cyrl catalogs and leaves other JSON alone', () => {
    const code = JSON.stringify({ title: 'Мастер на час' });
    const out = plugin.transform(code, '/repo/packages/i18n/src/catalogs/ru/common.json');
    expect(JSON.parse(out?.code ?? '{}')).toEqual({ title: nb('Мастер на~час') });
    expect(
      plugin.transform(code, '/repo/packages/i18n/src/catalogs/sr-Cyrl/jobs.json?import'),
    ).not.toBeNull();
    expect(plugin.transform(code, '/repo/packages/i18n/src/catalogs/sr-Latn/jobs.json')).toBeNull();
    expect(plugin.transform(code, '/repo/apps/tma/package.json')).toBeNull();
  });
});
