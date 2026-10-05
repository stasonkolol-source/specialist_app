// Подписи карточки специалиста S08–S09 (DEVELOPMENT_PLAN 4.5): сумма позиции в колонке цены,
// единица и длительность под названием, место и языки в шапке и «О себе».
import type { CardPhotoOut, CardServiceOut, SpecialistProfileOut } from '@sosed/api-client';
import type { PriceUnit } from '@sosed/domain';
import { servicePrice } from '@sosed/hooks';
import type { Format } from '@sosed/i18n';

import type { Language } from './paths.ts';
import { LANGUAGES } from './paths.ts';

/** Длительности позиции S36, минут: «до 1 часа», «1–2 часа», «полдня», «весь день». */
export const DURATIONS = [60, 120, 240, 480] as const;
export type Duration = (typeof DURATIONS)[number];

/** Сумма в колонке цены: «2 000 RSD», «от 2 500 RSD», «1 000–4 000 RSD», «договорная»;
 *  единица — в подписи под названием, как на артборде S09. */
export function priceAmount(format: Format, service: CardServiceOut): string {
  const price = servicePrice(service);
  if (price.type === 'fixed' || price.type === 'hourly' || price.type === 'per_unit') {
    return format.money(price.min ?? 0);
  }
  return format.price({ ...price, unit: null });
}

/** Единица позиции для подписи «за час», «за выезд»; почасовая — всегда «за час». */
export function serviceUnit(service: CardServiceOut): PriceUnit | null {
  const price = servicePrice(service);
  return price.type === 'hourly' ? 'hour' : (price.unit ?? null);
}

/** Длительность из пресетов S36; другое значение не подписываем. */
export function serviceDuration(service: CardServiceOut): Duration | null {
  return DURATIONS.find((minutes) => minutes === service.duration_min) ?? null;
}

/** Языки профиля, которые знает интерфейс, в порядке профиля. */
export function knownLanguages(card: Pick<SpecialistProfileOut, 'languages'>): Language[] {
  return card.languages.filter((code): code is Language =>
    (LANGUAGES as readonly string[]).includes(code),
  );
}

/** «русский, сербский» → «Русский, сербский»: список в строке с заглавной буквы. */
export function sentence(items: readonly string[]): string {
  const text = items.join(', ');
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** Где работает: основной район, без него — город. */
export function place(card: Pick<SpecialistProfileOut, 'district' | 'city'>): string | null {
  return card.district?.name ?? card.city?.name ?? null;
}

/** Фото для аватара `size` px: самый маленький вариант, которого хватит экрану плотностью 3x. */
export function avatarSrc(photo: CardPhotoOut | null, size: number): string | undefined {
  if (!photo) return undefined;
  const sorted = [...photo.variants].sort((a, b) => a.width - b.width);
  return (sorted.find((variant) => variant.width >= size * 3) ?? sorted.at(-1))?.url;
}
