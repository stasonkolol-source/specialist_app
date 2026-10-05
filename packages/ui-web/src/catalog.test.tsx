// Шторка, карточка специалиста и карточка заявки (DEVELOPMENT_PLAN 4.4, 5.3; макеты S05, S06, S13).
// Тексты — данные фикстур.
import { fireEvent, render, screen } from '@testing-library/react';
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';

import { SegmentedNav } from './form/Choice.tsx';
import { JobCard } from './JobCard.tsx';
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
  it('рейтинг с отзывами и район через одну «·», языки своей строкой, бейджи и цена; сердечко — кнопка', async () => {
    const onToggle = vi.fn();
    const { container } = render(
      <SpecialistCard
        name="Алексей Морозов"
        headline="Электрик · мелкий ремонт · люстры"
        rating="4,9"
        reviews="(37)"
        newLabel="Новый специалист"
        languages="рус., серб."
        meta={['Лиман, ≈ 1,5 км']}
        badges={[{ label: 'Сегодня до 20:00', tone: 'ok', dot: true }]}
        price="от 2 000 RSD"
        href="#s08"
        favorite={{ label: 'Добавить в избранное', active: false, onToggle }}
      />,
    );

    const link = screen.getByRole('link', { name: /Алексей Морозов/ });
    expect(link.getAttribute('href')).toBe('#s08');
    // точка — перед каждой частью строки рейтинга: первая обрезается, после района точки нет
    const rating = screen.getByText('(37)').closest('.overflow-hidden') as Element;
    expect(rating.textContent).toBe('·4,9(37)·Лиман, ≈ 1,5 км');
    // языки — своей строкой с иконкой, без «·»
    const languages = screen.getByText('рус., серб.').parentElement as Element;
    expect(languages.textContent).toBe('рус., серб.');
    expect(languages.querySelector('svg')).toBeTruthy();
    expect(screen.getByText('Сегодня до 20:00')).toBeTruthy();
    expect(screen.getByText('от 2 000 RSD')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Добавить в избранное' }));
    expect(onToggle).toHaveBeenCalledOnce();
    expect(await a11yViolations(container)).toEqual([]);
  });

  it('без отзывов — «Новый специалист», без фото — инициалы, без языков — строки нет', () => {
    const { container } = render(
      <SpecialistCard name="Ana Ilić" newLabel="Новый специалист" meta={[]} href="#s08" />,
    );

    expect(screen.getByRole('link').textContent).toContain('Новый специалист');
    expect(screen.getByRole('img', { name: 'Ana Ilić' }).textContent).toBe('AI');
    expect(container.querySelector('svg')).toBeNull();
  });

  it('подработка — серый бейдж «Подработка» в строке имени', () => {
    render(
      <SpecialistCard
        name="Иван Гаврилов"
        tag="Подработка"
        newLabel="Новый специалист"
        meta={['Лиман']}
        href="#s08"
      />,
    );

    const tag = screen.getByText('Подработка');
    expect(tag.parentElement?.textContent).toBe('Иван ГавриловПодработка');
    expect(tag.className).toContain('bg-bg2');
  });
});

describe('JobCard (S13)', () => {
  it('заголовок и бюджет, бейджи, описание, место и время, места; ссылка — вся карточка', async () => {
    const onOpen = vi.fn((event: { preventDefault: () => void }) => event.preventDefault());
    const { container } = render(
      <JobCard
        title="Повесить люстру"
        budget="5 000 RSD"
        badges={[
          { label: 'Сегодня 18–21', tone: 'info', icon: 'clock' },
          { label: 'Люстры', tone: 'mute' },
        ]}
        time="15 мин назад"
        description="Потолок бетонный, крюк есть."
        photos={[{ src: '' }, { src: '' }]}
        photoLabel={(number) => `Фото ${number}`}
        place="Лиман, ≈ 1,2 км"
        slots={{ taken: 3, total: 5, label: 'откликов 3 из 5' }}
        href="#s15"
        onOpen={onOpen}
      />,
    );

    const link = screen.getByRole('link', { name: /Повесить люстру/ });
    expect(link.getAttribute('href')).toBe('#s15');
    expect(screen.getByRole('heading', { name: 'Повесить люстру', level: 2 })).toBeTruthy();
    expect(screen.getByText('5 000 RSD')).toBeTruthy();
    expect(screen.getByText('Сегодня 18–21')).toBeTruthy();
    expect(screen.getByText('Лиман, ≈ 1,2 км')).toBeTruthy();
    expect(screen.getByText('откликов 3 из 5')).toBeTruthy();
    expect(screen.getAllByRole('img', { name: /^Фото \d$/ })).toHaveLength(2);
    // строки не зависят от длины текстов: бейджам — вся строка, время — в строке места, места —
    // своей строкой
    expect(screen.getByText('Сегодня 18–21').parentElement?.textContent).toBe(
      'Сегодня 18–21Люстры',
    );
    expect(screen.getByText('15 мин назад').parentElement?.textContent).toBe(
      'Лиман, ≈ 1,2 км15 мин назад',
    );
    expect(screen.getByText('откликов 3 из 5').parentElement?.textContent).toBe('откликов 3 из 5');
    // полоски мест — декорация: число мест читается подписью
    expect(container.querySelectorAll('[aria-hidden="true"] > i')).toHaveLength(5);
    expect(container.querySelectorAll('[aria-hidden="true"] > i.bg-accent')).toHaveLength(3);
    fireEvent.click(link);
    expect(onOpen).toHaveBeenCalledOnce();
    expect(await a11yViolations(container)).toEqual([]);
  });

  it('договорная — текстом без цены; без ссылки — статья', () => {
    render(
      <JobCard
        title="Течёт смеситель на кухне"
        budget="Договорная"
        negotiable
        badges={[{ label: 'Срочно', tone: 'urgent', icon: 'zap' }]}
        time="5 мин назад"
        slots={{ taken: 4, total: 5, label: 'откликов 4 из 5' }}
      />,
    );

    expect(screen.queryByRole('link')).toBeNull();
    expect(screen.getByRole('article')).toBeTruthy();
    expect(screen.getByText('Договорная').className).toContain('text-text2');
  });
});

describe('SegmentedNav (S13)', () => {
  it('ссылки разделов, текущий — aria-current; переход — через onNavigate', async () => {
    const onNavigate = vi.fn((_id: string, event: { preventDefault: () => void }) =>
      event.preventDefault(),
    );
    const { container } = render(
      <SegmentedNav
        label="Раздел заявок"
        current="feed"
        items={[
          { id: 'feed', label: 'Лента', href: '#feed' },
          { id: 'responses', label: 'Мои отклики', href: '#responses' },
          { id: 'mine', label: 'Мои заявки', href: '#mine' },
        ]}
        onNavigate={onNavigate}
      />,
    );

    const nav = screen.getByRole('navigation', { name: 'Раздел заявок' });
    expect(nav).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Лента' }).getAttribute('aria-current')).toBe('page');
    expect(
      screen.getByRole('link', { name: 'Мои заявки' }).getAttribute('aria-current'),
    ).toBeNull();
    fireEvent.click(screen.getByRole('link', { name: 'Мои заявки' }));
    expect(onNavigate).toHaveBeenCalledWith('mine', expect.anything());
    expect(await a11yViolations(container)).toEqual([]);
  });
});
