// Списки чипов S32b–c с раскрывашкой («Другие категории», «Ещё 4 района»). Выбранные при показе —
// первыми, как на артбордах, остальные — в порядке справочника; свёрнутый список — первые `count`
// и всё выбранное. Порядок меняется только при сворачивании: чип не уезжает из-под пальца.
import { useState } from 'react';

export function chipList<T extends { id: number }>(
  items: readonly T[],
  kept: ReadonlySet<number>,
  selected: ReadonlySet<number>,
  count: number,
): { ordered: T[]; collapsed: T[] } {
  const ordered = [
    ...items.filter((item) => kept.has(item.id)),
    ...items.filter((item) => !kept.has(item.id)),
  ];
  const collapsed = ordered.filter(
    (item, index) => index < count || kept.has(item.id) || selected.has(item.id),
  );
  return { ordered, collapsed };
}

export function useChipList<T extends { id: number }>(
  items: readonly T[],
  selected: readonly number[],
  count: number,
) {
  const [expanded, setExpanded] = useState(false);
  // выбранные при показе списка и при последнем сворачивании
  const [kept, setKept] = useState<ReadonlySet<number>>(() => new Set(selected));
  const { ordered, collapsed } = chipList(items, kept, new Set(selected), count);
  return {
    visible: expanded ? ordered : collapsed,
    expanded,
    /** Сколько скрыто в свёрнутом виде («Ещё N районов»); 0 — раскрывать нечего. */
    hidden: ordered.length - collapsed.length,
    toggle() {
      if (expanded) setKept(new Set(selected));
      setExpanded(!expanded);
    },
  };
}
