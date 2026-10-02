// Категория заявки в дереве каталога: подпись «Раздел → Услуга», как на чипе S20a и в превью S20d.
import type { CategoryOut } from '@sosed/api-client';

export function findCategory(tree: readonly CategoryOut[], id: number): CategoryOut | null {
  for (const node of tree) {
    if (node.id === id) return node;
    const found = findCategory(node.children, id);
    if (found) return found;
  }
  return null;
}

/** «Мастер на час → Люстры»; раздел без родителя — просто название; нет в дереве — null. */
export function categoryPath(tree: readonly CategoryOut[], id: number): string | null {
  for (const section of tree) {
    if (section.id === id) return section.name;
    const leaf = findCategory(section.children, id);
    if (leaf) return `${section.name} → ${leaf.name}`;
  }
  return null;
}
