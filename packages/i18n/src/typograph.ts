// Типограф каталогов: неразрывные пробелы там, где перенос рвёт смысл, — «Мастер на / час», «до 5 /
// исполнителей», строка, начатая с «— так безопаснее». Ставится при сборке (vite.ts): исходные JSON
// остаются читаемыми, бандл получает готовый текст, в рантайме — ни кода, ни работы. Меняются только
// пробелы: синтаксис ICU (аргументы {name}, заголовки plural/select, теги) проходит как есть, текст
// вариантов plural/select — обычный текст, `#` в нём — число.
import type { Catalog } from './catalog.ts';

const NBSP = String.fromCharCode(0xa0);

/** Предлоги, союзы и частицы, которые не должны висеть в конце строки (GLOSSARY.md). sr-Latn —
 *  транслитерация sr-Cyrl в рантайме и неразрывные пробелы наследует. */
const SHORT_WORDS = {
  ru: ['в', 'к', 'с', 'у', 'о', 'и', 'а', 'я', 'на', 'по', 'до', 'за', 'из', 'от', 'не'],
  'sr-Cyrl': ['и', 'у', 'с', 'а', 'о', 'к', 'на', 'за', 'од', 'до', 'по', 'не'],
} as const;

export type TypographLocale = keyof typeof SHORT_WORDS;

const SHORT = {
  ru: new Set<string>(SHORT_WORDS.ru),
  'sr-Cyrl': new Set<string>(SHORT_WORDS['sr-Cyrl']),
};

type Kind = 'text' | 'syntax' | 'number';

const LETTER = /\p{L}/u;
const DIGIT = /[0-9]/;
// «{name}», «{n, number}», «{n, plural,»: имя аргумента, тип и что дальше — «,» или «}»
const ARGUMENT = /^\{\s*\w+\s*(?:,\s*(\w+)\s*)?([,}])/;
const NESTED = new Set(['plural', 'selectordinal', 'select']);

/** Разметка сообщения ICU по символам: текст, синтаксис или число (`#` в варианте plural и
 *  аргумент `{n, number}`). Апострофы-кавычки ICU в каталогах не используются — это текст. */
function classify(message: string): Kind[] {
  const kinds: Kind[] = Array.from({ length: message.length }, () => 'text');
  const mark = (from: number, to: number, kind: Kind) => kinds.fill(kind, from, to);
  let i = 0;

  // Текст до «}» — конца варианта (на верхнем уровне — лишней скобки).
  function text(numbered: boolean): void {
    while (i < message.length && message[i] !== '}') {
      const ch = message[i];
      if (ch === '{') argument();
      else if (ch === '<' && /[\w/]/.test(message[i + 1] ?? '')) {
        const end = message.indexOf('>', i);
        const stop = end < 0 ? message.length : end + 1;
        mark(i, stop, 'syntax');
        i = stop;
      } else {
        if (ch === '#' && numbered) kinds[i] = 'number';
        i += 1;
      }
    }
  }

  function argument(): void {
    const start = i;
    const header = ARGUMENT.exec(message.slice(i));
    if (!header) {
      kinds[i] = 'syntax';
      i += 1;
      return;
    }
    const type = header[1];
    i += header[0].length;
    if (type !== undefined && NESTED.has(type) && header[2] === ',') {
      // «one {…} few {…}»: селекторы и скобки — синтаксис, внутри скобок — снова сообщение
      while (i < message.length && message[i] !== '}') {
        kinds[i] = 'syntax';
        if (message[i] === '{') {
          i += 1;
          text(type !== 'select');
          if (i < message.length) kinds[i] = 'syntax';
        }
        i += 1;
      }
      mark(start, start + header[0].length, 'syntax');
      if (i < message.length) kinds[i] = 'syntax';
      i += 1;
      return;
    }
    // {name}, {n, number}, {d, date, short}: целиком синтаксис, число — числом
    let depth = header[2] === '}' ? 0 : 1;
    while (i < message.length && depth > 0) {
      if (message[i] === '{') depth += 1;
      else if (message[i] === '}') depth -= 1;
      i += 1;
    }
    mark(start, i, type === 'number' ? 'number' : 'syntax');
  }

  while (i < message.length) {
    text(false);
    if (i < message.length) kinds[i] = 'syntax';
    i += 1;
  }
  return kinds;
}

/** Склеить ли пробел на позиции `i` со словом перед ним и после него. */
function glue(message: string, kinds: Kind[], i: number, short: Set<string>): boolean {
  const next = message[i + 1];
  if (next === undefined || next === '}' || /\s/.test(next)) return false;
  // тире не начинает строку
  if (next === '—') return true;
  // число и слово после него: «5 исполнителей», «# заявки», «{n, number} из»
  const prev = message[i - 1] ?? '';
  const number = kinds[i - 1] === 'number' || (kinds[i - 1] === 'text' && DIGIT.test(prev));
  if (number && kinds[i + 1] === 'text' && LETTER.test(next)) return true;
  // короткое слово — отдельное слово, а не конец длинного или «{n}й»
  let start = i;
  while (start > 0 && kinds[start - 1] === 'text' && LETTER.test(message[start - 1] ?? ''))
    start -= 1;
  if (start === i || i - start > 2) return false;
  const before = message[start - 1];
  if (before !== undefined && (LETTER.test(before) || DIGIT.test(before) || before === '}')) {
    return false;
  }
  return short.has(message.slice(start, i).toLowerCase());
}

/** Сообщение с неразрывными пробелами: меняются только пробелы текста. */
export function typographMessage(message: string, locale: TypographLocale): string {
  if (!message.includes(' ')) return message;
  const kinds = classify(message);
  const short = SHORT[locale];
  let out = '';
  for (let i = 0; i < message.length; i += 1) {
    const glued = message[i] === ' ' && kinds[i] === 'text' && glue(message, kinds, i, short);
    out += glued ? NBSP : message[i];
  }
  return out;
}

/** Каталог целиком: ключи и вложенность — как были. */
export function typographCatalog<T extends Catalog>(catalog: T, locale: TypographLocale): T {
  return Object.fromEntries(
    Object.entries(catalog).map(([key, value]) => [
      key,
      typeof value === 'string' ? typographMessage(value, locale) : typographCatalog(value, locale),
    ]),
  ) as T;
}
