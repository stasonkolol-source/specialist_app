// Сколько строк было в «Моих активных заявках» на Главной в прошлый раз — у этого же пользователя.
// Главная держит место под блок до ответа /me/jobs, только когда он, скорее всего, будет, и ровно
// под столько строк: у клиента без активных заявок (новый, всё закрыл) скелетон больше не исчезает
// через секунду после первого кадра, а плитки разделов не прыгают вверх (CLS). Подсказка — в
// localStorage этого устройства: нет её или он недоступен — место не держим.
const STORAGE_KEY = 'sosed:home-active-jobs';

export function rememberedRows(user: string): number {
  try {
    const saved: unknown = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? 'null');
    if (typeof saved !== 'object' || saved === null) return 0;
    const { user: owner, rows } = saved as { user?: unknown; rows?: unknown };
    return owner === user && typeof rows === 'number' && rows > 0 ? rows : 0;
  } catch {
    return 0;
  }
}

export function rememberRows(user: string, rows: number): void {
  try {
    if (rows > 0) localStorage.setItem(STORAGE_KEY, JSON.stringify({ user, rows }));
    else localStorage.removeItem(STORAGE_KEY);
  } catch {
    // приватный режим или квота: в следующий раз места под блок просто не будет
  }
}
