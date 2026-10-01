// Прайс-лист S35–S36 (DEVELOPMENT_PLAN 2.11): группы по категориям профиля, перенос позиции выше
// и ниже внутри группы (порядок — общий, PUT /me/profile/services/order) и цена позиции для
// форматирования. Без DOM: то же понадобится мобильному приложению.
import type { ServiceOut } from '@sosed/api-client';
import type { Price, PriceUnit } from '@sosed/domain';
import { SERVICE_UNITS } from '@sosed/domain';

export interface ServiceGroup {
  /** Категория группы; null — позиции без группы. */
  categoryId: number | null;
  items: ServiceOut[];
}

/**
 * Группы прайса: сначала категории профиля по его порядку, потом остальные категории позиций,
 * в конце — без группы; внутри — по `position`.
 */
export function groupServices(
  services: readonly ServiceOut[],
  categoryOrder: readonly number[],
): ServiceGroup[] {
  const sorted = [...services].sort((a, b) => a.position - b.position);
  const ids = [
    ...categoryOrder,
    ...sorted.map((service) => service.category_id).filter((id): id is number => id !== null),
  ];
  const groups: ServiceGroup[] = [...new Set(ids)].map((categoryId) => ({
    categoryId,
    items: sorted.filter((service) => service.category_id === categoryId),
  }));
  groups.push({
    categoryId: null,
    items: sorted.filter((service) => service.category_id === null),
  });
  return groups.filter((group) => group.items.length > 0);
}

/**
 * Новый порядок всего прайса, когда позиция `id` встаёт выше (-1) или ниже (+1) соседки по
 * группе; null — двигать некуда.
 */
export function moveService(
  services: readonly ServiceOut[],
  id: string,
  direction: -1 | 1,
): string[] | null {
  const order = [...services].sort((a, b) => a.position - b.position);
  const index = order.findIndex((service) => service.id === id);
  const current = order[index];
  if (!current) return null;
  let neighbour = index + direction;
  let other = order[neighbour];
  while (other && other.category_id !== current.category_id) {
    neighbour += direction;
    other = order[neighbour];
  }
  if (!other) return null;
  order[index] = other;
  order[neighbour] = current;
  return order.map((service) => service.id);
}

/** Цена позиции для `format.price`: суммы — в пара, как в API. */
export function servicePrice(service: ServiceOut): Price {
  const unit = SERVICE_UNITS.find((known) => known === service.unit) ?? null;
  return {
    type: service.price_type,
    min: service.price_min?.amount ?? null,
    max: service.price_max?.amount ?? null,
    unit: unit as PriceUnit | null,
  };
}
