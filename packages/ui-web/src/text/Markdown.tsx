// Markdown-текст документа (S48; позже S47, S50, S51): блоки из parseMarkdown на типошкале ui.css.
// Без innerHTML — только элементы React, поэтому текст с сервера не может вставить разметку или
// скрипт: сырой HTML остаётся видимым текстом.
import type { ReactNode } from 'react';
import { useMemo } from 'react';

import { FOCUS, cx } from '../cx.ts';
import type { Block, Inline } from './markdown.ts';
import { inlineText, parseMarkdown } from './markdown.ts';

const HEADING = {
  2: 'text-h3 pt-2',
  3: 'text-title pt-1',
  4: 'font-semibold',
} as const;

const CELL = 'border-0 border-b border-solid border-line py-2 pr-3 align-top text-left last:pr-0';

/** Столбцов больше — таблица не помещается в колонку телефона (≈ 290 px внутри карточки S48) и
 *  рвёт слова посередине. Такая таблица рисуется списком записей: первая ячейка — заголовок,
 *  остальные — «Столбец: значение». */
const MAX_TABLE_COLUMNS = 2;

export interface MarkdownBlocksProps {
  blocks: Block[];
  /** Уровень заголовков `##`: после h1 экрана — h2 (по умолчанию), внутри секции — h3. */
  headingLevel?: 2 | 3;
  /** Размер и цвет текста задаёт родитель (text-body, text-sm text-text2…): блоки их наследуют. */
  className?: string;
  /** Язык текста, если он не совпадает с языком интерфейса (перевода ещё нет). */
  lang?: string;
}

/** Готовые блоки: экран может разложить документ по-своему (S48 — пронумерованные разделы). */
export function MarkdownBlocks({ blocks, headingLevel = 2, className, lang }: MarkdownBlocksProps) {
  return (
    <div lang={lang} className={cx('flex flex-col gap-2 [overflow-wrap:anywhere]', className)}>
      {blocks.map((block, i) => renderBlock(block, i, headingLevel - 2))}
    </div>
  );
}

export interface MarkdownProps extends Omit<MarkdownBlocksProps, 'blocks'> {
  source: string;
}

export function Markdown({ source, className, ...rest }: MarkdownProps) {
  const blocks = useMemo(() => parseMarkdown(source), [source]);
  return (
    <MarkdownBlocks
      blocks={blocks}
      className={cx('gap-3 text-body text-text', className)}
      {...rest}
    />
  );
}

function renderBlock(block: Block, key: number, shift: number): ReactNode {
  switch (block.type) {
    case 'heading': {
      const Tag = `h${Math.min(block.level + shift, 4)}` as 'h2' | 'h3' | 'h4';
      return (
        <Tag key={key} className={cx('m-0 text-text', HEADING[block.level])}>
          {renderInline(block.children)}
        </Tag>
      );
    }
    case 'paragraph':
      return (
        <p key={key} className="m-0">
          {renderInline(block.children)}
        </p>
      );
    case 'list': {
      const items = block.items.map((item, i) => (
        <li key={i} className="pl-0.5">
          {renderInline(item)}
        </li>
      ));
      return block.ordered ? (
        <ol key={key} start={block.start} className="m-0 flex list-decimal flex-col gap-1 pl-5">
          {items}
        </ol>
      ) : (
        <ul key={key} className="m-0 flex list-disc flex-col gap-1 pl-5">
          {items}
        </ul>
      );
    }
    case 'quote':
      return (
        <blockquote
          key={key}
          className="m-0 border-0 border-l-4 border-solid border-line pl-3 text-text2"
        >
          {renderInline(block.children)}
        </blockquote>
      );
    case 'table':
      return block.head.length > MAX_TABLE_COLUMNS ? (
        <Records key={key} block={block} />
      ) : (
        <table key={key} className="w-full table-fixed border-collapse [overflow-wrap:break-word]">
          <thead>
            <tr>
              {block.head.map((cell, i) => (
                <th key={i} scope="col" className={cx(CELL, 'font-semibold')}>
                  {renderInline(cell)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {block.rows.map((row, r) => (
              <tr key={r} className="[&:last-child>td]:border-b-0">
                {row.map((cell, i) => (
                  <td key={i} className={CELL}>
                    {renderInline(cell)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      );
    case 'rule':
      return <hr key={key} className="m-0 border-0 border-t border-solid border-line" />;
  }
}

/** Широкая таблица списком: строка — запись, подписи значений — заголовки столбцов. */
function Records({ block }: { block: Extract<Block, { type: 'table' }> }) {
  const labels = block.head.slice(1).map(inlineText);
  return (
    <ul className="m-0 flex list-none flex-col p-0">
      {block.rows.map(([first = [], ...rest], r) => (
        <li
          key={r}
          className="flex flex-col gap-0.5 border-0 border-b border-solid border-line py-2 first:pt-0 last:border-b-0 last:pb-0"
        >
          <span className="font-semibold text-text">{renderInline(first)}</span>
          {rest.map((cell, i) => (
            <span key={i}>
              <span className="font-medium">{labels[i]}:</span> {renderInline(cell)}
            </span>
          ))}
        </li>
      ))}
    </ul>
  );
}

function renderInline(nodes: Inline[]): ReactNode[] {
  return nodes.map((node, i) => {
    switch (node.type) {
      case 'text':
        return node.value;
      case 'strong':
        return (
          <strong key={i} className="font-semibold">
            {renderInline(node.children)}
          </strong>
        );
      case 'em':
        return <em key={i}>{renderInline(node.children)}</em>;
      case 'code':
        return (
          <code key={i} className="rounded-badge bg-bg2 px-1">
            {node.value}
          </code>
        );
      case 'link':
        return (
          <a
            key={i}
            href={node.href}
            className={cx('font-semibold text-accent underline', FOCUS)}
            {...(/^https?:/i.test(node.href)
              ? { target: '_blank', rel: 'noopener noreferrer' }
              : {})}
          >
            {renderInline(node.children)}
          </a>
        );
    }
  });
}
