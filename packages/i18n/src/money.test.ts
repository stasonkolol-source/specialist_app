// Поле суммы: ни вставка «1.500,00», ни набор «1500.00» не дают ×100 (ADV-10); тысячи — как в выводе
// цен языка (UXM-9).
import { describe, expect, it } from 'vitest';

import { createFormat } from './format.ts';
import { moneyInput, moneyPara, moneyValue } from './money.ts';

const NBSP = String.fromCharCode(0xa0);
const ru = (raw: string) => moneyInput(raw, 'ru').replaceAll(NBSP, ' ');

describe('moneyInput ru: тысячи пробелом, дробь — запятой (или точкой по привычке)', () => {
  it.each([
    ['5000', '5 000'],
    ['1234567', '1 234 567'],
    ['1.500,00', '1 500,'],
    ['1500.00', '1 500,'],
    ['1 500,50', '1 500,'],
    ['12,5', '12,'],
    ['1.500', '1 500'],
    ['１５００', '1 500'],
    ['-5', '5'],
    ['007', '7'],
    ['0,50', ''],
    ['1000000000', '100 000 000'],
  ])('%s → %s', (raw, shown) => {
    expect(ru(raw)).toBe(shown);
  });

  it('набор по символу: цифры после запятой не дописываются к целым', () => {
    let text = '';
    for (const key of '1500,50') text = moneyInput(text + key, 'ru');
    expect(text.replaceAll(NBSP, ' ')).toBe('1 500,');
    expect(moneyValue(text, 'ru')).toBe(1500);
  });
});

describe.each(['sr-Latn', 'sr-Cyrl'] as const)(
  'moneyInput %s: тысячи точкой, дробь запятой',
  (locale) => {
    it.each([
      ['1234567', '1.234.567'],
      ['1.500,00', '1.500,'],
      ['1500.00', '1.500,'],
      ['1 500,50', '1.500,'],
      ['12,5', '12,'],
      ['1.500', '1.500'],
      // стёрли последний ноль в «1.500» — это тысячи, а не 1,50 динара
      ['1.50', '150'],
      ['1.234.56', '123.456'],
    ])('%s → %s', (raw, shown) => {
      expect(moneyInput(raw, locale)).toBe(shown);
    });

    it('тысячи — как у вывода цен языка', () => {
      const money = createFormat(locale).money(123_456_700);
      expect(money.startsWith(moneyInput('1234567', locale))).toBe(true);
    });
  },
);

describe('moneyValue: целые динары из текста поля', () => {
  it.each([
    ['ru', '1 500,', 1500],
    ['ru', '1500.00', 1500],
    ['sr-Latn', '1.500', 1500],
    ['sr-Latn', '1500.00', 1500],
    ['sr-Cyrl', '1.500,99', 1500],
    ['ru', '', null],
    ['ru', '0', null],
  ] as const)('%s %s → %s', (locale, text, value) => {
    expect(moneyValue(text, locale)).toBe(value);
  });

  it('прайс S36 — до пара: дробь сохраняется, ×100 нет', () => {
    expect(moneyInput('1500.00', 'sr-Latn', 2)).toBe('1.500,00');
    expect(moneyInput('1.500,5', 'sr-Cyrl', 2)).toBe('1.500,5');
    expect(moneyInput('2000.5', 'ru', 2).replaceAll(NBSP, ' ')).toBe('2 000,5');
    expect(moneyInput('0,29', 'ru', 2)).toBe('0,29');
    expect(moneyPara('1500.00', 'ru')).toBe(150_000);
    expect(moneyPara('1.500,00', 'sr-Latn')).toBe(150_000);
    expect(moneyPara('2 000,5', 'ru')).toBe(200_050);
    expect(moneyPara('0,29', 'sr-Latn')).toBe(29);
    expect(moneyPara('', 'ru')).toBeNull();
  });

  it('повторный разбор не меняет текст поля', () => {
    for (const locale of ['ru', 'sr-Latn', 'sr-Cyrl'] as const) {
      for (const raw of ['1.500,00', '1500.00', '1 500,50', '1234567', '1.50']) {
        for (const decimals of [0, 2]) {
          const once = moneyInput(raw, locale, decimals);
          expect(moneyInput(once, locale, decimals)).toBe(once);
        }
      }
    }
  });
});
