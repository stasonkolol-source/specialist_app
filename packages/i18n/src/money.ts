// Сумма в поле ввода — одна на все денежные поля (S20c бюджет, S16/S24 цена отклика, S19, S06,
// S32c, S36): тысячи — как в выводе цен (ru «1 500», sr «1.500»), дробь — после запятой. Копеек в
// продукте нет: поля — целые динары; только прайс S36 хранит цену до пара (уже сохранённые цены с
// парами не округляем). Раньше поля выбрасывали всё, кроме цифр, и «1.500,00» или «1500.00»
// становились 150 000 (ADV-10).
import type { Locale } from './locale.ts';

const NBSP = String.fromCharCode(0xa0);

/** Разделитель тысяч в поле — как у Intl для языка: ru — неразрывный пробел, sr — точка. */
const GROUP: Record<Locale, string> = { ru: NBSP, 'sr-Latn': '.', 'sr-Cyrl': '.' };

/** Цифр в сумме: до 999 999 999 динаров. */
const MONEY_DIGITS = 9;

/** Где начинается дробная часть, или -1. Запятая — десятичный знак в обоих языках. Точка в ru —
 *  дробная, если за ней 0–2 цифры («1500.00», «12.5», «1 500.» — набирают дробь), и тысячи перед
 *  тремя («1.500»). В sr точка — наш же разделитель тысяч: дробная, только если тысячами быть не
 *  может — 1–2 цифры после сплошных четырёх и больше («1500.00»); «1.50» после стирания нуля в
 *  «1.500» — тысячи, «150». */
function fractionAt(text: string, locale: Locale): number {
  const comma = text.lastIndexOf(',');
  if (comma >= 0) return comma;
  const dot = text.lastIndexOf('.');
  if (dot < 0) return -1;
  const before = text.slice(0, dot).trim();
  const after = text.slice(dot + 1).trim();
  const fraction = locale === 'ru' ? /^\d{0,2}$/.test(after) : /^\d{1,2}$/.test(after);
  return fraction && (locale === 'ru' || /^\d{4,}$/.test(before)) ? dot : -1;
}

/** Текст поля суммы из набранного или вставленного: «1.500,00», «1500.00», «1 500,50» → «1 500»
 *  (ru) или «1.500» (sr). Без `decimals` копейки отбрасываются, а набранный десятичный знак
 *  остаётся в конце («1 500,»), чтобы цифры после него не дописались к целым; с `decimals: 2` —
 *  до двух знаков дроби («2 000,50»). Не-цифры и ведущие нули — прочь, полноширинные цифры —
 *  обычные. Повторный вызов на результате его не меняет. */
export function moneyInput(raw: string, locale: Locale, decimals = 0): string {
  const text = raw.normalize('NFKC');
  const at = fractionAt(text, locale);
  const whole = at >= 0 ? text.slice(0, at) : text;
  const digits = whole.replace(/\D/g, '').replace(/^0+/, '').slice(0, MONEY_DIGITS);
  const grouped = digits.replace(/\B(?=(\d{3})+(?!\d))/g, GROUP[locale]);
  if (at < 0) return grouped;
  if (decimals === 0) return digits ? `${grouped},` : '';
  const fraction = text
    .slice(at + 1)
    .replace(/\D/g, '')
    .slice(0, decimals);
  return `${grouped || '0'},${fraction}`;
}

/** Целые динары из текста поля; пусто или ноль — null. */
export function moneyValue(text: string, locale: Locale): number | null {
  const value = Number(moneyInput(text, locale).replace(/\D/g, ''));
  return value > 0 ? value : null;
}

/** Пара из текста поля с копейками (прайс S36): «2 000,5» → 200 050; пусто или ноль — null. */
export function moneyPara(text: string, locale: Locale): number | null {
  const [whole = '', fraction = ''] = moneyInput(text, locale, 2).split(',');
  const para = Number(whole.replace(/\D/g, '')) * 100 + Number(fraction.padEnd(2, '0'));
  return para > 0 ? para : null;
}
