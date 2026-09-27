// UUID ⇄ base62 ровно 22 символа (ARCHITECTURE §11.4). Алфавит 0-9A-Za-z, старшие разряды слева,
// дополнение нулями слева. Тот же кодек в backend (модуль growth) — сверка по golden.json.

export const BASE62_ALPHABET = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz';
export const BASE62_UUID_LENGTH = 22;

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const BASE62_RE = /^[0-9A-Za-z]{22}$/;
const MAX_UUID = (1n << 128n) - 1n;

export function isUuid(value: string): boolean {
  return UUID_RE.test(value);
}

export function uuidToBase62(uuid: string): string {
  if (!isUuid(uuid)) throw new TypeError(`Не UUID: «${uuid}»`);
  let n = BigInt(`0x${uuid.replaceAll('-', '')}`);
  let out = '';
  while (n > 0n) {
    out = BASE62_ALPHABET[Number(n % 62n)] + out;
    n /= 62n;
  }
  return out.padStart(BASE62_UUID_LENGTH, '0');
}

/** Канонический UUID в нижнем регистре; `null`, если строка не base62-UUID. */
export function base62ToUuid(value: string): string | null {
  if (!BASE62_RE.test(value)) return null;
  let n = 0n;
  for (const ch of value) n = n * 62n + BigInt(BASE62_ALPHABET.indexOf(ch));
  if (n > MAX_UUID) return null;
  const hex = n.toString(16).padStart(32, '0');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}
