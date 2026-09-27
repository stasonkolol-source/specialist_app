// Минимальный разбор WOFF2: достаёт таблицу cmap и проверяет, есть ли в файле глиф для символа.
// Нужен тесту подмножеств шрифтов: unicode-range в CSS — обещание, cmap — факт.
import { brotliDecompressSync } from 'node:zlib';

const CMAP_TAG_INDEX = 0;
const GLYF_TAG_INDEX = 10;
const LOCA_TAG_INDEX = 11;

function readBase128(buf: Buffer, pos: number): [number, number] {
  let value = 0;
  for (let i = 0; i < 5; i += 1) {
    const byte = buf.readUInt8(pos + i);
    value = value * 128 + (byte & 0x7f);
    if ((byte & 0x80) === 0) return [value, pos + i + 1];
  }
  throw new Error('WOFF2: некорректный UIntBase128');
}

function extractCmap(woff2: Buffer): Buffer {
  if (woff2.toString('latin1', 0, 4) !== 'wOF2') throw new Error('Не WOFF2');
  const numTables = woff2.readUInt16BE(12);
  const compressedSize = woff2.readUInt32BE(20);
  let pos = 48;
  let offset = 0;
  let cmap: { offset: number; length: number } | undefined;
  for (let i = 0; i < numTables; i += 1) {
    const flags = woff2.readUInt8(pos);
    pos += 1;
    const tagIndex = flags & 0x3f;
    const transform = flags >> 6;
    if (tagIndex === 63) pos += 4;
    let length: number;
    [length, pos] = readBase128(woff2, pos);
    const glyfOrLoca = tagIndex === GLYF_TAG_INDEX || tagIndex === LOCA_TAG_INDEX;
    if ((glyfOrLoca && transform === 0) || (!glyfOrLoca && transform !== 0)) {
      [length, pos] = readBase128(woff2, pos);
    }
    if (tagIndex === CMAP_TAG_INDEX) cmap = { offset, length };
    offset += length;
  }
  if (!cmap) throw new Error('WOFF2: нет таблицы cmap');
  const data = brotliDecompressSync(woff2.subarray(pos, pos + compressedSize));
  return data.subarray(cmap.offset, cmap.offset + cmap.length);
}

function format4Has(t: Buffer, at: number, cp: number): boolean {
  if (cp > 0xffff) return false;
  const segCount = t.readUInt16BE(at + 6) / 2;
  const ends = at + 14;
  const starts = ends + segCount * 2 + 2;
  const deltas = starts + segCount * 2;
  const rangeOffsets = deltas + segCount * 2;
  for (let i = 0; i < segCount; i += 1) {
    if (cp > t.readUInt16BE(ends + i * 2)) continue;
    const start = t.readUInt16BE(starts + i * 2);
    if (cp < start) return false;
    const delta = t.readUInt16BE(deltas + i * 2);
    const roAt = rangeOffsets + i * 2;
    const ro = t.readUInt16BE(roAt);
    if (ro === 0) return ((cp + delta) & 0xffff) !== 0;
    const glyph = t.readUInt16BE(roAt + ro + (cp - start) * 2);
    return glyph !== 0 && ((glyph + delta) & 0xffff) !== 0;
  }
  return false;
}

function format12Has(t: Buffer, at: number, cp: number): boolean {
  const groups = t.readUInt32BE(at + 12);
  for (let i = 0; i < groups; i += 1) {
    const g = at + 16 + i * 12;
    if (cp >= t.readUInt32BE(g) && cp <= t.readUInt32BE(g + 4)) return true;
  }
  return false;
}

/** Функция «есть ли глиф для кодовой точки» по cmap файла WOFF2 (Unicode-подтаблица 3/1, 3/10 или 0/*). */
export function woff2Coverage(woff2: Buffer): (codePoint: number) => boolean {
  const cmap = extractCmap(woff2);
  const count = cmap.readUInt16BE(2);
  const subtables: number[] = [];
  for (let i = 0; i < count; i += 1) {
    const rec = 4 + i * 8;
    const platform = cmap.readUInt16BE(rec);
    const encoding = cmap.readUInt16BE(rec + 2);
    if (platform === 0 || (platform === 3 && (encoding === 1 || encoding === 10))) {
      subtables.push(cmap.readUInt32BE(rec + 4));
    }
  }
  if (subtables.length === 0) throw new Error('WOFF2: нет Unicode-подтаблицы cmap');
  return (cp) =>
    subtables.some((at) => {
      const format = cmap.readUInt16BE(at);
      if (format === 4) return format4Has(cmap, at, cp);
      if (format === 12) return format12Has(cmap, at, cp);
      return false;
    });
}
