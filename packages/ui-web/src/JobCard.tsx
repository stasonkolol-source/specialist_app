// .card.tight + .job-t + .slots: карточка заявки в ленте (S13, D13). Строки приходят готовыми —
// бюджет, «5 мин назад», место и счётчик откликов форматирует экран (@sosed/i18n), компонент
// раскладывает их по макету: заголовок и бюджет, бейджи срочности и категории, начало описания,
// до трёх превью и строка «место · полоски мест» (на узком экране места — второй строкой).
import type { MouseEvent } from 'react';

import type { BadgeTone } from './Badge.tsx';
import { Badge } from './Badge.tsx';
import { Price } from './Chips.tsx';
import { FOCUS, cx } from './cx.ts';
import type { IconName } from './icon/Icon.tsx';
import { Icon } from './icon/Icon.tsx';
import { Photo } from './Photo.tsx';

export interface JobCardBadge {
  label: string;
  tone: BadgeTone;
  icon?: IconName;
}

export interface JobSlots {
  taken: number;
  total: number;
  /** «откликов 3 из 5». */
  label: string;
}

export interface JobCardProps {
  title: string;
  /** «5 000 RSD», «4 000–6 000 RSD» или «Договорная» (`negotiable`). */
  budget: string;
  negotiable?: boolean;
  badges: readonly JobCardBadge[];
  /** «15 мин назад». */
  time: string;
  description?: string | null;
  photos?: readonly { src: string; placeholder?: string | null }[];
  /** Подпись превью для скринридера: «Фото 1». */
  photoLabel?: (index: number) => string;
  /** «Лиман, ≈ 1,2 км». */
  place?: string | null;
  slots: JobSlots;
  /** Заявка S15; без него карточка не ссылка. */
  href?: string;
  /** Переход внутри приложения: роутер отменяет переход браузера. */
  onOpen?: (event: MouseEvent<HTMLAnchorElement>) => void;
  /** Уровень заголовка по месту на экране: в ленте после h1 — h2. */
  titleAs?: 'h2' | 'h3';
}

export function JobCard({
  title,
  budget,
  negotiable = false,
  badges,
  time,
  description,
  photos = [],
  photoLabel,
  place,
  slots,
  href,
  onOpen,
  titleAs: Title = 'h2',
}: JobCardProps) {
  const content = (
    <>
      <span className="flex items-start justify-between gap-3">
        <Title className="m-0 text-title">{title}</Title>
        {negotiable ? (
          <span className="shrink-0 font-semibold whitespace-nowrap text-text2">{budget}</span>
        ) : (
          <Price>{budget}</Price>
        )}
      </span>
      <span className="flex items-center justify-between gap-3">
        <span className="flex min-w-0 flex-wrap gap-1.5">
          {badges.map((badge) => (
            <Badge key={badge.label} tone={badge.tone} icon={badge.icon}>
              {badge.label}
            </Badge>
          ))}
        </span>
        <span className="shrink-0 text-cap text-text2">{time}</span>
      </span>
      {description && <span className="line-clamp-3 text-sm text-text2">{description}</span>}
      {photos.length > 0 && (
        <span className="flex gap-2">
          {photos.map((photo, index) => (
            <Photo
              key={`${index}-${photo.src}`}
              src={photo.src}
              placeholder={photo.placeholder}
              alt={photoLabel?.(index + 1) ?? ''}
              sizes="56px"
              className="size-14"
            />
          ))}
        </span>
      )}
      {/* место не сжимается: не хватает строки — места уходят на вторую, вправо */}
      <span className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
        {place && (
          <span className="flex max-w-full shrink-0 items-center gap-1.5 text-cap text-text2">
            <Icon name="pin" size={16} className="shrink-0" />
            <span className="truncate">{place}</span>
          </span>
        )}
        <span className="ml-auto flex shrink-0 items-center gap-1.5">
          <span aria-hidden="true" className="flex gap-0.75">
            {Array.from({ length: slots.total }, (_, index) => (
              <i
                key={index}
                className={cx(
                  'h-1.5 w-3.5 rounded-full',
                  index < slots.taken ? 'bg-accent' : 'bg-line',
                )}
              />
            ))}
          </span>
          <span className="text-cap text-text2">{slots.label}</span>
        </span>
      </span>
    </>
  );
  const classes = 'flex flex-col gap-2 rounded-card bg-surface p-4 text-text';
  return href ? (
    <a href={href} onClick={onOpen} className={cx(classes, 'press-card', FOCUS)}>
      {content}
    </a>
  ) : (
    <article className={classes}>{content}</article>
  );
}
