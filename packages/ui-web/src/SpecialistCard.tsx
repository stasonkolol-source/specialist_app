// .card.tight + .sp: карточка специалиста в выдаче (S05). Строки приходят готовыми — рейтинг,
// расстояние и цену форматирует экран (@sosed/i18n), компонент раскладывает их по макету:
// фото или инициалы, имя (у подработки — серый бейдж «Подработка» рядом), «коротко о себе»,
// рейтинг с числом отзывов или «Новый специалист» и район через «·» (Rating — точка не повисает
// на краю строки), языки словами — своей строкой с иконкой, бейджи-факты и цена «от». Сердечко
// «в избранное» — поверх карточки.
import type { MouseEvent } from 'react';

import { Avatar } from './Avatar.tsx';
import type { BadgeTone } from './Badge.tsx';
import { Badge } from './Badge.tsx';
import { IconButton } from './Button.tsx';
import { Price } from './Chips.tsx';
import { FOCUS, cx } from './cx.ts';
import type { IconName } from './icon/Icon.tsx';
import { Icon } from './icon/Icon.tsx';
import { Rating } from './Rating.tsx';

export interface SpecialistBadge {
  label: string;
  tone: BadgeTone;
  icon?: IconName;
  dot?: boolean;
}

export interface SpecialistCardProps {
  name: string;
  /** «Подработка» — серый бейдж в строке имени: профиль подработки (SPEC §4). */
  tag?: string | null;
  headline?: string | null;
  photo?: { src: string; placeholder?: string | null } | null;
  /** «4,9» — рейтинг, когда отзывов достаточно; иначе `newLabel`. */
  rating?: string | null;
  /** «(37)» в выдаче, «37 отзывов» на Главной — сразу за рейтингом, без «·». */
  reviews?: string | null;
  /** «Новый специалист» — вместо рейтинга. */
  newLabel: string;
  /** Языки словами — своей строкой с иконкой: «рус., серб.». */
  languages?: string | null;
  /** Через «·» после рейтинга: «Лиман, ≈ 1,5 км». */
  meta: readonly string[];
  badges?: readonly SpecialistBadge[];
  /** «от 2 000 RSD». */
  price?: string | null;
  /** Профиль S08; без него карточка не ссылка (до 4.5 профиля ещё нет). */
  href?: string;
  /** Переход внутри приложения: роутер отменяет переход браузера. */
  onOpen?: (event: MouseEvent<HTMLAnchorElement>) => void;
  favorite?: { label: string; active: boolean; onToggle: () => void };
}

export function SpecialistCard({
  name,
  tag,
  headline,
  photo,
  rating,
  reviews,
  newLabel,
  languages,
  meta,
  badges = [],
  price,
  href,
  onOpen,
  favorite,
}: SpecialistCardProps) {
  const head = cx('flex items-start gap-3 text-text', href && FOCUS);
  const content = (
    <>
      <Avatar name={name} src={photo?.src} placeholder={photo?.placeholder} />
      <span className="flex min-w-0 grow flex-col gap-0.5">
        {/* длинное имя переносится, бейдж уходит строкой ниже, а не сжимается */}
        <span className={cx('flex flex-wrap items-center gap-2', favorite && 'pr-8')}>
          <span className="text-title">{name}</span>
          {tag && <Badge>{tag}</Badge>}
        </span>
        {headline && <span className="text-sm text-text2">{headline}</span>}
        <Rating value={rating} reviews={reviews} newLabel={newLabel} meta={meta} />
        {languages && (
          <span className="flex items-center gap-1.5 text-cap text-text2">
            <Icon name="languages" size={16} />
            <span className="min-w-0 truncate">{languages}</span>
          </span>
        )}
      </span>
    </>
  );
  return (
    <article className="relative flex flex-col gap-2 rounded-card bg-surface p-4 text-text">
      {href ? (
        <a href={href} onClick={onOpen} className={head}>
          {content}
        </a>
      ) : (
        <div className={head}>{content}</div>
      )}
      {favorite && (
        <IconButton
          plain
          icon="heart"
          label={favorite.label}
          active={favorite.active}
          aria-pressed={favorite.active}
          onClick={favorite.onToggle}
          className="absolute top-1 right-1"
        />
      )}
      {(badges.length > 0 || price) && (
        <div
          className={cx(
            'flex items-end gap-2',
            badges.length > 0 ? 'justify-between' : 'justify-end',
          )}
        >
          {badges.length > 0 && (
            <span className="flex flex-wrap gap-1.5">
              {badges.map((badge) => (
                <Badge key={badge.label} tone={badge.tone} icon={badge.icon} dot={badge.dot}>
                  {badge.label}
                </Badge>
              ))}
            </span>
          )}
          {price && <Price>{price}</Price>}
        </div>
      )}
    </article>
  );
}
