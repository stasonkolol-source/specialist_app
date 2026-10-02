// Список карточек ленты S13 — виртуальный (DEVELOPMENT_PLAN 5.3): в DOM только карточки у экрана и
// запас по краям, остальное — высотой контейнера; прокрутка тысячи заявок не тормозит. Высоты
// разные (фото, описание) — список меряет отрисованные карточки сам. Прокручивается окно, как у
// всех экранов: отступ списка от начала страницы пересчитывается, когда меняется шапка.
import type { JobCardOut } from '@sosed/api-client';
import { useWindowVirtualizer } from '@tanstack/react-virtual';
import type { ReactNode } from 'react';
import { useLayoutEffect, useRef, useState } from 'react';

/** Карточка с отступом до следующей: без фото — около 170 px, с фото — около 240. */
const ESTIMATED_CARD = 190;
/** Карточек за краем экрана: быстрая прокрутка не показывает пустоту. */
const OVERSCAN = 4;

export function FeedList({
  cards,
  render,
}: {
  cards: readonly JobCardOut[];
  render: (card: JobCardOut) => ReactNode;
}) {
  const list = useRef<HTMLDivElement>(null);
  const [margin, setMargin] = useState(0);
  // шапка над списком меняется (строка «N заявок», баннер) — экран меняет размер, отступ мерится
  // заново; то же значение React не перерисовывает
  useLayoutEffect(() => {
    const element = list.current;
    if (!element) return undefined;
    const measure = () =>
      setMargin(Math.round(element.getBoundingClientRect().top + window.scrollY));
    measure();
    if (typeof ResizeObserver === 'undefined' || !element.parentElement) return undefined;
    const observer = new ResizeObserver(measure);
    observer.observe(element.parentElement);
    return () => observer.disconnect();
  }, []);
  const virtualizer = useWindowVirtualizer({
    count: cards.length,
    estimateSize: () => ESTIMATED_CARD,
    overscan: OVERSCAN,
    scrollMargin: margin,
    getItemKey: (index) => cards[index]?.id ?? index,
  });
  return (
    <div ref={list} className="relative" style={{ height: virtualizer.getTotalSize() }}>
      {virtualizer.getVirtualItems().map((item) => {
        const card = cards[item.index];
        if (!card) return null;
        return (
          <div
            key={item.key}
            ref={virtualizer.measureElement}
            data-index={item.index}
            className="absolute inset-x-0 top-0 pb-2.5"
            style={{ transform: `translateY(${item.start - margin}px)` }}
          >
            {render(card)}
          </div>
        );
      })}
    </div>
  );
}
