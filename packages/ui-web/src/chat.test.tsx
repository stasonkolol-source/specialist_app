// Чат 6.4: пузыри по сторонам, системные строки, подписи дней, маска контактов, композер. Тексты —
// фикстуры.
import { fireEvent, render, screen } from '@testing-library/react';
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';

import { Bubble, ChatList, Composer, DayLabel, MASK, MaskedText, SystemNote } from './Chat.tsx';
import { a11yViolations } from './testing/a11y.ts';

const HIDDEN = { label: 'контакт скрыт', hiddenLabel: 'Контакт скрыт до договорённости' };

describe('ChatList, Bubble, SystemNote, DayLabel, MaskedText', () => {
  it('свои справа акцентом, чужие слева; маска — плашкой; повтор неотправленного', async () => {
    const retry = vi.fn();
    const { container } = render(
      <ChatList label="Сообщения">
        <DayLabel dateTime="2026-10-02">2 октября</DayLabel>
        <SystemNote icon="lock">Контакты откроются после договорённости</SystemNote>
        <Bubble side="in" time="16:04">
          <MaskedText text={`Позвоните мне: ${MASK}`} {...HIDDEN} />
        </Bubble>
        <Bubble side="out" time="16:07">
          Отлично, давайте в 19:00!
        </Bubble>
        <Bubble side="out" failed status="Не отправлено — нажмите, чтобы повторить" onRetry={retry}>
          Жду
        </Bubble>
      </ChatList>,
    );

    const log = screen.getByRole('log', { name: 'Сообщения' });
    expect(log.getAttribute('aria-live')).toBe('polite');
    expect(screen.getByText('2 октября').getAttribute('dateTime')).toBe('2026-10-02');
    // «•••» сервера — словами с замком; диктору — полнее, видимые слова от него скрыты
    expect(screen.queryByText(MASK)).toBeNull();
    const chip = screen.getByText('контакт скрыт');
    expect(chip.getAttribute('aria-hidden')).toBe('true');
    expect(chip.parentElement?.className).toContain('text-text2');
    expect(chip.parentElement?.querySelector('svg')).toBeTruthy();
    expect(screen.getByText('Контакт скрыт до договорённости').className).toContain('sr-only');
    expect(screen.getByText('Позвоните мне:', { exact: false })).toBeTruthy();
    expect(screen.getByText('Отлично, давайте в 19:00!').className).toContain('self-end');
    fireEvent.click(screen.getByRole('button', { name: /Жду/ }));
    expect(retry).toHaveBeenCalledOnce();
    expect(await a11yViolations(container)).toEqual([]);
  });

  it('в своём пузыре плашка маски — темнее акцента, цветом текста пузыря', () => {
    render(
      <Bubble side="out" time="16:07">
        <MaskedText text={`Мой номер ${MASK}, звоните`} side="out" {...HIDDEN} />
      </Bubble>,
    );

    const chip = screen.getByText('контакт скрыт').parentElement;
    expect(chip?.className).toContain('bg-[rgb(0_0_0/0.16)]');
    expect(chip?.className).not.toContain('text-text2');
    expect(screen.getByText(/звоните/)).toBeTruthy();
  });
});

describe('Composer', () => {
  function Controlled({ onSend }: { onSend: (text: string) => void }) {
    const [value, setValue] = useState('');
    return (
      <Composer
        value={value}
        onChange={setValue}
        onSend={() => {
          onSend(value);
          setValue('');
        }}
        placeholder="Сообщение"
        label="Сообщение Ане"
        sendLabel="Отправить"
        maxLength={4000}
      />
    );
  }

  it('пустое не отправляет; Enter — отправка, Shift+Enter — перенос строки', async () => {
    const onSend = vi.fn();
    const { container } = render(<Controlled onSend={onSend} />);
    const field = screen.getByLabelText('Сообщение Ане');
    const send = screen.getByRole('button', { name: 'Отправить' });

    expect((send as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(field, { target: { value: '   ' } });
    fireEvent.keyDown(field, { key: 'Enter' });
    expect(onSend).not.toHaveBeenCalled();

    fireEvent.change(field, { target: { value: 'Добрый день!' } });
    fireEvent.keyDown(field, { key: 'Enter', shiftKey: true });
    expect(onSend).not.toHaveBeenCalled();
    fireEvent.keyDown(field, { key: 'Enter' });
    expect(onSend).toHaveBeenCalledWith('Добрый день!');
    expect((field as HTMLTextAreaElement).value).toBe('');

    fireEvent.change(field, { target: { value: 'Ещё' } });
    fireEvent.click(send);
    expect(onSend).toHaveBeenLastCalledWith('Ещё');
    expect(await a11yViolations(container)).toEqual([]);
  });
});
