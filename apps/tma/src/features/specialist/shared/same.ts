/** Одни и те же значения в том же порядке: сохранять нечего. */
export function sameList<T>(a: readonly T[], b: readonly T[]): boolean {
  return a.length === b.length && a.every((value, index) => value === b[index]);
}
