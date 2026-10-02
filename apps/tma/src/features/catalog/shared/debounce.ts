// Значение с задержкой: «Показать N» в шторке S06 считает, когда человек перестал нажимать, —
// иначе каждый чип тратил бы запрос из лимита гостя (60 в минуту).
import { useEffect, useState } from 'react';

export function useDebounced<T>(value: T, delayMs: number): T {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setSettled(value), delayMs);
    return () => clearTimeout(timer);
  }, [value, delayMs]);
  return settled;
}
