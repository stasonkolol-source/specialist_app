import { act, render } from '@testing-library/react';
import type { ReactNode } from 'react';
import { describe, expect, it } from 'vitest';

import { createMockPlatform } from './mock.ts';
import {
  PlatformProvider,
  useBackButton,
  useBottomButtonState,
  useClosingConfirmation,
  useColorSchemeOverride,
  useMainButton,
  useSecondaryButton,
  useThemeSync,
} from './react.tsx';
import type { Platform } from './types.ts';

function setup(version = '9.1') {
  const mock = createMockPlatform({ version });
  const wrap = (ui: ReactNode, platform: Platform = mock.platform) => (
    <PlatformProvider platform={platform}>{ui}</PlatformProvider>
  );
  return { ...mock, wrap };
}

describe('useMainButton', () => {
  it('показывает кнопку, ловит нажатие, прячет при размонтировании', () => {
    const { platform, telegram, wrap } = setup();
    const clicks: string[] = [];
    function Screen() {
      useMainButton({ text: 'Далее', onClick: () => clicks.push('next') });
      return null;
    }
    const view = render(wrap(<Screen />));
    expect(platform.mainButton.getState()).toMatchObject({ text: 'Далее', visible: true });
    act(() => telegram.emit('main_button_pressed'));
    expect(clicks).toEqual(['next']);
    view.unmount();
    expect(platform.mainButton.getState().visible).toBe(false);
    expect(telegram.callsOf('web_app_setup_main_button').at(-1)).toMatchObject({
      is_visible: false,
    });
  });
});

describe('useSecondaryButton', () => {
  it('до 7.10 — кнопка в контенте', () => {
    const { wrap } = setup('7.0');
    const clicks: number[] = [];
    let native: boolean | undefined;
    function Screen() {
      native = useSecondaryButton({ text: 'Написать', onClick: () => clicks.push(1) }).native;
      const state = useBottomButtonState('secondary');
      return state.visible && !state.native ? (
        <button type="button" onClick={state.click}>
          {state.text}
        </button>
      ) : null;
    }
    const view = render(wrap(<Screen />));
    expect(native).toBe(false);
    act(() => view.getByRole('button', { name: 'Написать' }).click());
    expect(clicks).toEqual([1]);
  });
});

describe('useBackButton', () => {
  it('сначала закрывает шторку, потом экран; без обработчиков кнопка скрыта', () => {
    const { telegram, wrap } = setup();
    const events: string[] = [];
    function Sheet() {
      useBackButton(() => events.push('sheet'));
      return null;
    }
    function Screen({ sheet }: { sheet: boolean }) {
      useBackButton(() => events.push('screen'));
      return sheet ? <Sheet /> : null;
    }
    const view = render(wrap(<Screen sheet />));
    act(() => telegram.emit('back_button_pressed'));
    view.rerender(wrap(<Screen sheet={false} />));
    act(() => telegram.emit('back_button_pressed'));
    expect(events).toEqual(['sheet', 'screen']);
    view.unmount();
    expect(telegram.callsOf('web_app_setup_back_button').at(-1)).toEqual({ is_visible: false });
  });

  it('null — кнопки нет', () => {
    const { telegram, wrap } = setup();
    function Root() {
      useBackButton(null);
      return null;
    }
    render(wrap(<Root />));
    expect(telegram.callsOf('web_app_setup_back_button')).toEqual([]);
  });
});

describe('useClosingConfirmation', () => {
  it('включается, пока есть хотя бы один потребитель', () => {
    const { telegram, wrap } = setup();
    function Form({ dirty }: { dirty: boolean }) {
      useClosingConfirmation(dirty);
      return null;
    }
    const view = render(wrap(<Form dirty />));
    view.rerender(wrap(<Form dirty={false} />));
    expect(telegram.callsOf('web_app_setup_closing_behavior')).toEqual([
      { need_confirmation: true },
      { need_confirmation: false },
    ]);
  });
});

describe('useThemeSync', () => {
  it('data-theme и цвета клиента по colorScheme и themeChanged', () => {
    const { telegram, wrap } = setup();
    const chrome = {
      light: { header: '#FFFFFF', background: '#F2F3F5', bottomBar: '#FFFFFF' },
      dark: { header: '#17212B', background: '#0E1621', bottomBar: '#17212B' },
    };
    function App() {
      useThemeSync(chrome);
      return null;
    }
    render(wrap(<App />));
    expect(document.documentElement.dataset.theme).toBe('light');
    act(() => telegram.setColorScheme('dark'));
    expect(document.documentElement.dataset.theme).toBe('dark');
    expect(telegram.callsOf('web_app_set_header_color').at(-1)).toEqual({ color: '#17212B' });
    expect(telegram.callsOf('web_app_set_bottom_bar_color').at(-1)).toEqual({ color: '#17212B' });
  });

  it('экран со своей темой перекрашивает приложение и клиент, после — снова тема Telegram', () => {
    const { telegram, wrap } = setup();
    const chrome = {
      light: { header: '#FFFFFF', background: '#F2F3F5', bottomBar: '#FFFFFF' },
      dark: { header: '#17212B', background: '#0E1621', bottomBar: '#17212B' },
    };
    function Viewer() {
      useColorSchemeOverride('dark');
      return null;
    }
    function App({ viewer }: { viewer: boolean }) {
      useThemeSync(chrome);
      return viewer ? <Viewer /> : null;
    }
    const view = render(wrap(<App viewer />));
    expect(document.documentElement.dataset.theme).toBe('dark');
    expect(telegram.callsOf('web_app_set_header_color').at(-1)).toEqual({ color: '#17212B' });

    view.rerender(wrap(<App viewer={false} />));

    expect(document.documentElement.dataset.theme).toBe('light');
    expect(telegram.callsOf('web_app_set_header_color').at(-1)).toEqual({ color: '#FFFFFF' });
  });
});
