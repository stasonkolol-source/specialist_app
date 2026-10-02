// .card.tight + .sp: карточка специалиста в выдаче (S05). Строки приходят готовыми — рейтинг,
// расстояние и цену форматирует экран (@sosed/i18n), компонент раскладывает их по макету:
// фото или инициалы, имя, «коротко о себе», рейтинг с числом отзывов или «Новый специалист»,
// район и языки, бейджи-факты и цена «от». Сердечко «в избранное» — поверх карточки.
import type { MouseEvent } from 'react';

import { Avatar } from './Avatar.tsx';
import type { BadgeTone } from './Badge.tsx';
import { Badge } from './Badge.tsx';
import { IconButton } from './Button.tsx';
import { Price } from './Chips.tsx';
import { FOCUS, cx } from './cx.ts';
import type { IconName } from './icon/Icon.tsx';
import { Icon } from './icon/Icon.tsx';

export interface SpecialistBadge {
  label: string;
  tone: BadgeTone;
  icon?: IconName;
  dot?: boolean;
}

export interface SpecialistCardProps {
  name: string;
  headline?: string | null;
  photo?: { src: string; placeholder?: string | null } | null;
  /** «4,9» — рейтинг, когда отзывов достаточно; иначе `newLabel`. */
  rating?: string | null;
  /** «(37)» — число отзывов рядом с рейтингом. */
  reviews?: string | null;
  /** «Новый специалист» — вместо рейтинга. */
  newLabel: string;
  /** Через точку после рейтинга: «Лиман, ≈ 1,5 км», «ru, sr». */
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
  headline,
  photo,
  rating,
  reviews,
  newLabel,
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
        <span className={cx('text-title', favorite && 'pr-8')}>{name}</span>
        {headline && <span className="text-sm text-text2">{headline}</span>}
        <span className="flex flex-wrap items-center gap-1.5 text-cap text-text2">
          {rating ? (
            <>
              <span className="inline-flex items-center gap-0.75 font-semibold text-text">
                <Icon name="star" size={16} className="text-star" />
                {rating}
              </span>
              {reviews && <span>{reviews}</span>}
            </>
          ) : (
            <span>{newLabel}</span>
          )}
          {meta.map((item) => (
            <MetaItem key={item} text={item} />
          ))}
        </span>
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

function MetaItem({ text }: { text: string }) {
  return (
    <>
      <span aria-hidden="true">·</span>
      <span>{text}</span>
    </>
  );
}
