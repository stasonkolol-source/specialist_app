// Колонка цены позиции прайса — S09 и блок «Цены» на S08: сумма, под ней единица («за час»).
// Единица стоит у числа, а не серой подписью слева в ≈200 px от него: одинаковые суммы с разными
// единицами («2 000 RSD за визит» и «2 000 RSD за час») не путаются.
import type { CardServiceOut } from '@sosed/api-client';
import { useFormat, useTranslation } from '@sosed/i18n';
import { Price } from '@sosed/ui-web';

import { priceAmount, serviceUnit } from '../shared/card.ts';

export function PriceColumn({ service }: { service: CardServiceOut }) {
  const format = useFormat();
  const { t: common } = useTranslation();
  const unit = serviceUnit(service);
  return (
    <span className="flex shrink-0 flex-col items-end">
      <Price>{priceAmount(format, service)}</Price>
      {unit && <span className="text-cap text-text2">{common(`unit.${unit}`)}</span>}
    </span>
  );
}
