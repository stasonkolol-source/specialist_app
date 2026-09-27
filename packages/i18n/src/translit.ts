// Сербская кириллица → латиница (ADR-0013): однозначно, обратное направление — нет («injekcija»).

// prettier-ignore
const MAP: Record<string, string> = {
  А: 'A', Б: 'B', В: 'V', Г: 'G', Д: 'D', Ђ: 'Đ', Е: 'E', Ж: 'Ž', З: 'Z', И: 'I', Ј: 'J',
  К: 'K', Л: 'L', Љ: 'Lj', М: 'M', Н: 'N', Њ: 'Nj', О: 'O', П: 'P', Р: 'R', С: 'S', Т: 'T',
  Ћ: 'Ć', У: 'U', Ф: 'F', Х: 'H', Ц: 'C', Ч: 'Č', Џ: 'Dž', Ш: 'Š',
  а: 'a', б: 'b', в: 'v', г: 'g', д: 'd', ђ: 'đ', е: 'e', ж: 'ž', з: 'z', и: 'i', ј: 'j',
  к: 'k', л: 'l', љ: 'lj', м: 'm', н: 'n', њ: 'nj', о: 'o', п: 'p', р: 'r', с: 's', т: 't',
  ћ: 'ć', у: 'u', ф: 'f', х: 'h', ц: 'c', ч: 'č', џ: 'dž', ш: 'š',
};

const DIGRAPHS = new Set(['Љ', 'Њ', 'Џ']);

function isUpper(ch: string | undefined): boolean {
  return ch !== undefined && ch !== ch.toLowerCase() && ch === ch.toUpperCase();
}

function isLetter(ch: string | undefined): boolean {
  return ch !== undefined && ch.toLowerCase() !== ch.toUpperCase();
}

/**
 * «Љубав» → «Ljubav», «ЉУБАВ» → «LJUBAV». Заглавный диграф пишется целиком заглавными, если рядом
 * заглавная буква (слово набрано капсом). Символы не из сербской кириллицы остаются как есть.
 */
export function cyrToLat(text: string): string {
  const chars = [...text];
  return chars
    .map((ch, i) => {
      const lat = MAP[ch];
      if (lat === undefined) return ch;
      if (!DIGRAPHS.has(ch)) return lat;
      const next = chars[i + 1];
      const prev = chars[i - 1];
      const caps = isLetter(next) ? isUpper(next) : isUpper(prev);
      return caps ? lat.toUpperCase() : lat;
    })
    .join('');
}
