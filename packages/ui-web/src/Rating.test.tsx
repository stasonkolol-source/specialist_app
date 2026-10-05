// Строка рейтинга исполнителя (S23–S26) и строка через «·». Тексты — данные фикстур.
import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { MetaLine, Rating } from './Rating.tsx';

/** Текст строки, как его прочитает скринридер: точки-разделители скрыты. */
const spoken = (element: Element) => {
  const copy = element.cloneNode(true) as Element;
  copy.querySelectorAll('[aria-hidden="true"]').forEach((node) => node.remove());
  return copy.textContent;
};

describe('Rating', () => {
  it('звезда, число и число отзывов без точки между ними, дальше — район через «·»', () => {
    const { container } = render(
      <Rating value="4,9" reviews="37 отзывов" newLabel="Новый специалист" meta={['Лиман']} />,
    );
    const line = container.firstElementChild as Element;
    // точка перед рейтингом — первая в строке, она обрезается; между числом и отзывами её нет
    expect(line.textContent).toBe('·4,937 отзывов·Лиман');
    expect(spoken(line)).toBe('4,937 отзывовЛиман');
    expect(line.querySelector('svg')?.getAttribute('class')).toContain('text-star');
  });

  it('без рейтинга — «Новый специалист», пустые части пропускаются', () => {
    const { container } = render(
      <Rating
        value={null}
        reviews="0 отзывов"
        newLabel="Новый специалист"
        meta={[null, 'Лиман']}
      />,
    );
    const line = container.firstElementChild as Element;
    expect(spoken(line)).toBe('Новый специалистЛиман');
    expect(line.textContent).not.toContain('отзывов');
    expect(line.querySelector('svg')).toBeNull();
  });
});

describe('MetaLine', () => {
  it('ставит «·» перед каждой частью: первая в строке обрезается, а не висит в конце', () => {
    const { container } = render(<MetaLine parts={['Никола Петрович', '', 'сегодня в 09:00']} />);
    const dots = container.querySelectorAll('[aria-hidden="true"]');
    expect(dots).toHaveLength(2);
    // каждая точка — перед своей частью, после последней части точки нет
    expect(dots[1]?.nextSibling?.textContent).toBe('сегодня в 09:00');
    expect(container.textContent?.endsWith('сегодня в 09:00')).toBe(true);
    expect(container.firstElementChild?.getAttribute('class')).toContain('overflow-hidden');
  });
});
