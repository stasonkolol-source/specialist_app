// .sp-meta + .rate из ui.css: рейтинг исполнителя там, где клиент выбирает (S23–S26), — звезда,
// число жирным и «37 отзывов» серым, между ними без «·»; дальше через «·» район или роль. Рейтинга
// нет (отзывов меньше трёх) — «Новый специалист». Строки приходят готовыми: число и склонение
// форматирует экран (@sosed/i18n).
import type { ReactNode } from 'react';

import { cx } from './cx.ts';
import { Icon } from './icon/Icon.tsx';

export interface RatingProps {
  /** «4,9» — когда отзывов достаточно; нет — вместо рейтинга `newLabel`. */
  value?: string | null;
  /** «37 отзывов» — сразу за числом. */
  reviews?: string | null;
  /** «Новый специалист». */
  newLabel: string;
  /** После рейтинга через «·»: «Лиман», «исполнитель»; пустые пропускаются. */
  meta?: readonly (string | null | undefined)[];
  className?: string;
}

export function Rating({ value, reviews, newLabel, meta = [], className }: RatingProps) {
  const rating = value ? (
    <span className="flex flex-wrap items-center gap-x-1.5">
      <span className="inline-flex items-center gap-0.75 font-semibold text-text">
        <Icon name="star" size={16} className="text-star" />
        {value}
      </span>
      {reviews && <span>{reviews}</span>}
    </span>
  ) : (
    newLabel
  );
  return <MetaLine parts={[rating, ...meta]} className={cx('text-cap text-text2', className)} />;
}

/** Части строки через «·», перенос — между частями. Точка не повисает на краю строки: она стоит
 *  перед каждой частью, а у первой части каждой строки уходит за левый край и обрезается. */
export function MetaLine({
  parts,
  className,
}: {
  parts: readonly ReactNode[];
  className?: string;
}) {
  const shown = parts.filter(
    (part) => part !== null && part !== undefined && part !== false && part !== '',
  );
  return (
    <span className={cx('block overflow-hidden', className)}>
      <span className="-ml-4 flex flex-wrap items-center">
        {shown.map((part, index) => (
          <span key={index} className="flex items-center">
            <span aria-hidden="true" className="w-4 shrink-0 text-center">
              ·
            </span>
            {part}
          </span>
        ))}
      </span>
    </span>
  );
}
