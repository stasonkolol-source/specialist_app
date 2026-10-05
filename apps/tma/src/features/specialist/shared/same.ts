/** Одни и те же значения в том же порядке: сохранять нечего. */
export function sameList<T>(a: readonly T[], b: readonly T[]): boolean {
  return a.length === b.length && a.every((value, index) => value === b[index]);
}

/** Те же значения в любом порядке: районы профиля — набор («весь город» шлёт их по алфавиту
 *  языка интерфейса, а сервер хранит в своём порядке). */
export function sameSet<T>(a: readonly T[], b: readonly T[]): boolean {
  return a.length === b.length && a.every((value) => b.includes(value));
}
