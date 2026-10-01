// Общее для прайса S35–S36: лимит позиций, названия категорий и подписи цены.
import type { CategoryOut, ServiceOut } from '@sosed/api-client';
import type { Format } from '@sosed/i18n';
import { servicePrice } from '@sosed/hooks';

/** MAX_ITEMS прайса (backend pricing/domain/service.py). */
export const MAX_PRICE_ITEMS = 50;
/** Длительности S36, минут: «до 1 часа», «1–2 часа», «полдня», «весь день». */
export const DURATIONS = [60, 120, 240, 480] as const;

/** Названия всех категорий каталога по id: группы прайса — категории профиля. */
export function categoryNames(tree: readonly CategoryOut[]): Map<number, string> {
  const names = new Map<number, string>();
  const walk = (nodes: readonly CategoryOut[]) => {
    for (const node of nodes) {
      names.set(node.id, node.name);
      walk(node.children);
    }
  };
  walk(tree);
  return names;
}

/** Сумма позиции в колонке цены: «2 000 RSD», «от 1 500 RSD», «1 000–4 000 RSD»; единица — в
 *  подписи под названием («за час»), как на артборде S35. */
export function priceAmount(format: Format, service: ServiceOut, negotiable: string): string {
  const price = servicePrice(service);
  if (price.type === 'negotiable') return negotiable;
  if (price.type === 'from' || price.type === 'range') return format.price(price);
  return format.money(price.min ?? 0);
}
