// .tabbar / .tab / .tab.on / .cnt / .tab-plus: пять вкладок, центральная «+» создаёт заявку.
import type { MouseEvent } from 'react';

import { FOCUS, PRESS, cx } from './cx.ts';
import type { IconName } from './icon/Icon.tsx';
import { Icon } from './icon/Icon.tsx';

export interface TabItem {
  id: string;
  label: string;
  icon: IconName;
  href: string;
  /** Счётчик непрочитанного; 0 и undefined — без бейджа. */
  count?: number;
  /** Подпись счётчика для скринридера («3 новых»). */
  countLabel?: string;
}

export interface TabBarProps {
  items: TabItem[];
  activeId: string;
  /** Кнопка «+» в центре (S20a). */
  plus?: { id: string; label: string; href: string };
  /** aria-label навигации («Разделы»). */
  label: string;
  /** Переход внутри приложения: id вкладки или «+». href — только адрес ссылки, путём
   *  маршрута он бывает не всегда: у hash history в Telegram это «/#/jobs». */
  onNavigate?: (id: string, event: MouseEvent<HTMLAnchorElement>) => void;
  /** fixed — внизу экрана приложения; static — в галерее и артбордах. */
  position?: 'fixed' | 'static';
  className?: string;
}

export function TabBar({
  items,
  activeId,
  plus,
  label,
  onNavigate,
  position = 'fixed',
  className,
}: TabBarProps) {
  const middle = Math.floor(items.length / 2);
  const tabs = items.map((item) => {
    const on = item.id === activeId;
    return (
      <a
        key={item.id}
        href={item.href}
        onClick={onNavigate ? (e) => onNavigate(item.id, e) : undefined}
        aria-current={on ? 'page' : undefined}
        className={cx(
          'relative flex h-13 flex-col items-center justify-center gap-0.5 rounded-btn text-tab',
          on ? 'text-accent' : 'text-text2',
          FOCUS,
        )}
      >
        <Icon name={item.icon} size={24} />
        {item.label}
        {item.count ? (
          <span
            className="absolute top-px left-1/2 ml-1.25 h-4.5 min-w-4.5 rounded-full bg-urgent px-1.25 text-center text-tab leading-4.5 font-bold text-urgent-ink"
            aria-label={item.countLabel}
          >
            {item.count}
          </span>
        ) : null}
      </a>
    );
  });
  if (plus) {
    tabs.splice(
      middle,
      0,
      <a
        key="plus"
        href={plus.href}
        aria-label={plus.label}
        onClick={onNavigate ? (e) => onNavigate(plus.id, e) : undefined}
        className={cx('flex h-13 items-start justify-center rounded-btn', PRESS, FOCUS)}
      >
        <span className="mt-1 flex h-11 w-14 items-center justify-center rounded-btn bg-accent text-accent-ink">
          <Icon name="plus" size={24} />
        </span>
      </a>,
    );
  }
  return (
    <nav
      aria-label={label}
      className={cx(
        'grid h-21 grid-cols-5 border-t border-line bg-bg px-1.5 pt-1 pb-7',
        position === 'fixed' && 'fixed inset-x-0 bottom-0 z-10',
        className,
      )}
    >
      {tabs}
    </nav>
  );
}
