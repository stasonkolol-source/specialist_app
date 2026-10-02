// Шторка и карточка специалиста (DEVELOPMENT_PLAN 4.4, макеты S05, S06). Тексты — данные фикстур.
import { fireEvent, render, screen } from '@testing-library/react';
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';

import { Sheet } from './Sheet.tsx';
import { SpecialistCard } from './SpecialistCard.tsx';
import { a11yViolations } from './testing/a11y.ts';

function Filters({ onClose }: { onClose?: () => void }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        Фильтры
      </button>
      <Sheet
        open={open}
        title="Фильтры"
        closeLabel="Закрыть фильтры"
        onClose={() => {
          onClose?.();
          setOpen(false);
        }}
        footer={<button type="button">Показать 4 специалиста</button>}
      >
        <label>
          Цена до <input />
        </label>
      </Sheet>
    </>
  );
}

describe('Sheet (S06)', () => {
  it('модальный диалог с заголовком; фокус внутри и по кругу', async () => {
    const { container } = render(<Filters />);
    const opener = screen.getByRole('button', { name: 'Фильтры' });
    opener.focus();
    fireEvent.click(opener);

    const dialog = screen.getByRole('dialog', { name: 'Фильтры' });
    expect(dialog.getAttribute('aria-modal')).toBe('true');
    expect(document.activeElement).toBe(dialog);
    const last = screen.getByRole('button', { name: 'Показать 4 специалиста' });
    last.focus();
    fireEvent.keyDown(dialog, { key: 'Tab' });
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Закрыть фильтры' }));
    fireEvent.keyDown(dialog, { key: 'Tab', shiftKey: true });
    expect(document.activeElement).toBe(last);
    expect(await a11yViolations(container)).toEqual([]);
  });

  it('Escape, крестик и затемнение закрывают; фокус — на кнопку, что открыла', () => {
    const onClose = vi.fn();
    const { container } = render(<Filters onClose={onClose} />);
    const opener = screen.getByRole('button', { name: 'Фильтры' });

    for (const close of [
      () => fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' }),
      () => fireEvent.click(screen.getByRole('button', { name: 'Закрыть фильтры' })),
      () => fireEvent.click(container.querySelector('.bg-scrim') as Element),
    ]) {
      opener.focus();
      fireEvent.click(opener);
      close();
      expect(screen.queryByRole('dialog')).toBeNull();
      expect(document.activeElement).toBe(opener);
    }
    expect(onClose).toHaveBeenCalledTimes(3);
  });
});

describe('SpecialistCard (S05)', () => {
  it('рейтинг с отзывами, район и языки, бейджи и цена; сердечко — кнопка', async () => {
    const onToggle = vi.fn();
    const { container } = render(
      <SpecialistCard
        name="Алексей Морозов"
        headline="Электрик · мелкий ремонт · люстры"
        rating="4,9"
        reviews="(37)"
        newLabel="Новый специалист"
        meta={['Лиман, ≈ 1,5 км', 'ru, sr']}
        badges={[{ label: 'Сегодня до 20:00', tone: 'ok', dot: true }]}
        price="от 2 000 RSD"
        href="#s08"
        favorite={{ label: 'Добавить в избранное', active: false, onToggle }}
      />,
    );

    const link = screen.getByRole('link', { name: /Алексей Морозов/ });
    expect(link.getAttribute('href')).toBe('#s08');
    expect(link.textContent).toContain('4,9(37)·Лиман, ≈ 1,5 км·ru, sr');
    expect(screen.getByText('Сегодня до 20:00')).toBeTruthy();
    expect(screen.getByText('от 2 000 RSD')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Добавить в избранное' }));
    expect(onToggle).toHaveBeenCalledOnce();
    expect(await a11yViolations(container)).toEqual([]);
  });

  it('без отзывов — «Новый специалист», без фото — инициалы', () => {
    render(<SpecialistCard name="Ana Ilić" newLabel="Новый специалист" meta={[]} href="#s08" />);

    expect(screen.getByRole('link').textContent).toContain('Новый специалист');
    expect(screen.getByRole('img', { name: 'Ana Ilić' }).textContent).toBe('AI');
  });
});
