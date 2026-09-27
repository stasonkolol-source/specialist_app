// Документ S48 по разделам: макет показывает правила пронумерованными пунктами (.num-ic, жирный
// заголовок, текст .cap). Раздел — заголовок `## N. …` и всё до следующего такого заголовка;
// текст до первого раздела — вступление.
import type { MarkdownBlock, MarkdownInline } from '@sosed/ui-web';
import { parseMarkdown } from '@sosed/ui-web';

export interface LegalSection {
  /** Номер из заголовка «3. Переписка»; у раздела без номера («Контакты») — null. */
  number: string | null;
  title: MarkdownInline[];
  blocks: MarkdownBlock[];
}

export interface LegalOutline {
  intro: MarkdownBlock[];
  sections: LegalSection[];
}

const NUMBERED = /^(\d{1,3})\.\s+/;

export function outline(body: string): LegalOutline {
  const intro: MarkdownBlock[] = [];
  const sections: LegalSection[] = [];
  for (const block of parseMarkdown(body)) {
    if (block.type === 'heading' && block.level === 2) {
      sections.push({ ...splitNumber(block.children), blocks: [] });
    } else {
      (sections.at(-1)?.blocks ?? intro).push(block);
    }
  }
  return { intro, sections };
}

function splitNumber(title: MarkdownInline[]): Omit<LegalSection, 'blocks'> {
  const [first, ...rest] = title;
  const match = first?.type === 'text' ? NUMBERED.exec(first.value) : null;
  if (!first || first.type !== 'text' || !match) return { number: null, title };
  const text = first.value.slice(match[0].length);
  return {
    number: match[1] ?? null,
    title: text ? [{ type: 'text', value: text }, ...rest] : rest,
  };
}
