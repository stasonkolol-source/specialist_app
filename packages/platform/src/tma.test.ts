// Адаптер tma на mock-клиенте Telegram (mockTelegramEnv).
import { describe, expect, it } from 'vitest';

import { createMockPlatform } from './mock.ts';

const tick = () => new Promise((r) => setTimeout(r, 5));

describe('launch и версии', () => {
  it('launch params, сырой initData и language_code', () => {
    const { platform } = createMockPlatform({
      version: '8.0',
      languageCode: 'sr',
      startParam: 'j_abc',
    });
    expect(platform.kind).toBe('mock');
    expect(platform.launch.version).toBe('8.0');
    expect(platform.launch.languageCode).toBe('sr');
    expect(platform.launch.startParam).toBe('j_abc');
    expect(platform.launch.rawInitData).toContain('hash=mock');
    expect(platform.isVersionAtLeast('7.10')).toBe(true);
    expect(platform.isVersionAtLeast('9.0')).toBe(false);
  });

  it('настоящий initData вместо синтетического — вход на dev-стенде из браузера', () => {
    const signed =
      'auth_date=1790000000&signature=dev&user=%7B%22id%22%3A7%2C%22first_name%22%3A%22A%22%7D&hash=abc';
    const { platform } = createMockPlatform({ initData: signed });
    expect(platform.launch.rawInitData).toBe(signed);
  });

  it('startapp из адреса, когда кнопка бота открыла приложение без start_param', () => {
    window.history.replaceState(null, '', '/?startapp=l_terms');
    try {
      expect(createMockPlatform({}).platform.launch.startParam).toBe('l_terms');
      // подписанный параметр запуска важнее адреса
      expect(createMockPlatform({ startParam: 'h' }).platform.launch.startParam).toBe('h');
    } finally {
      window.history.replaceState(null, '', '/');
    }
  });

  it('возможности по версии Bot API', () => {
    expect(createMockPlatform({ version: '7.0' }).platform.capabilities).toMatchObject({
      secondaryButton: false,
      deviceStorage: false,
      cloudStorage: true,
    });
    expect(createMockPlatform({ version: '9.0' }).platform.capabilities).toMatchObject({
      secondaryButton: true,
      deviceStorage: true,
      safeArea: true,
    });
  });
});

describe('тема и вьюпорт', () => {
  it('colorScheme по bg_color и themeChanged', async () => {
    const { platform, telegram } = createMockPlatform({ colorScheme: 'dark' });
    expect(platform.theme.colorScheme()).toBe('dark');
    const seen: string[] = [];
    platform.theme.onChange((s) => seen.push(s));
    telegram.setColorScheme('light');
    expect(platform.theme.colorScheme()).toBe('light');
    expect(seen).toEqual(['light']);
  });

  it('viewportStableHeight, safe area и content safe area от клиента', async () => {
    const { platform } = createMockPlatform();
    await tick();
    expect(platform.viewport.stableHeight()).toBe(780);
    expect(platform.viewport.safeArea()).toEqual({ top: 47, right: 0, bottom: 34, left: 0 });
    expect(platform.viewport.contentSafeArea().top).toBe(46);
  });

  it('цвета шапки, фона и нижней панели', () => {
    const { platform, telegram } = createMockPlatform({ version: '8.0' });
    platform.theme.setHeaderColor('#ffffff');
    platform.theme.setBottomBarColor('#ffffff');
    expect(telegram.callsOf('web_app_set_header_color')).toEqual([{ color: '#ffffff' }]);
    expect(telegram.callsOf('web_app_set_bottom_bar_color')).toEqual([{ color: '#ffffff' }]);
  });
});

describe('кнопки', () => {
  it('MainButton: параметры клиенту и нажатие', () => {
    const { platform, telegram } = createMockPlatform();
    const clicks: number[] = [];
    platform.mainButton.onClick(() => clicks.push(1));
    platform.mainButton.set({ text: 'Откликнуться', visible: true, color: '#0B7A5F' });
    expect(telegram.callsOf('web_app_setup_main_button').at(-1)).toMatchObject({
      text: 'Откликнуться',
      is_visible: true,
      is_active: true,
      is_progress_visible: false,
      color: '#0B7A5F',
    });
    telegram.emit('main_button_pressed');
    expect(clicks).toHaveLength(1);
  });

  it('SecondaryButton до 7.10 — в контенте, клиенту не отправляется', () => {
    const { platform, telegram } = createMockPlatform({ version: '7.7' });
    expect(platform.secondaryButton.native).toBe(false);
    platform.secondaryButton.set({ text: 'Написать', visible: true });
    expect(telegram.callsOf('web_app_setup_secondary_button')).toEqual([]);
    const clicks: number[] = [];
    platform.secondaryButton.onClick(() => clicks.push(1));
    platform.secondaryButton.click();
    expect(clicks).toHaveLength(1);
  });

  it('SecondaryButton с 7.10 — нативная', () => {
    const { platform, telegram } = createMockPlatform({ version: '7.10' });
    platform.secondaryButton.set({ text: 'Написать', visible: true, position: 'left' });
    expect(telegram.callsOf('web_app_setup_secondary_button').at(-1)).toMatchObject({
      position: 'left',
    });
  });

  it('BackButton', () => {
    const { platform, telegram } = createMockPlatform();
    const clicks: number[] = [];
    platform.backButton.onClick(() => clicks.push(1));
    platform.backButton.setVisible(true);
    telegram.emit('back_button_pressed');
    expect(telegram.callsOf('web_app_setup_back_button')).toEqual([{ is_visible: true }]);
    expect(clicks).toHaveLength(1);
  });
});

describe('диалоги и запросы', () => {
  it('popup и confirm', async () => {
    expect(
      await createMockPlatform({ popupAnswer: 'delete' }).platform.popup({ message: 'Удалить?' }),
    ).toBe('delete');
    expect(
      await createMockPlatform({ popupAnswer: null }).platform.popup({ message: 'x' }),
    ).toBeNull();
    expect(await createMockPlatform({ popupAnswer: 'ok' }).platform.confirm('Точно?')).toBe(true);
    expect(await createMockPlatform({ popupAnswer: 'cancel' }).platform.confirm('Точно?')).toBe(
      false,
    );
  });

  it('requestWriteAccess, requestContact, shareMessage', async () => {
    const { platform } = createMockPlatform({ writeAccess: false });
    expect(await platform.requestWriteAccess()).toBe(false);
    expect(await platform.requestContact()).toBe(true);
    expect(await platform.shareMessage('prepared-1')).toBe(true);
  });

  it('shareContact: спрашивает телефон и отдаёт подписанный ответ Telegram', async () => {
    const { platform, telegram } = createMockPlatform({ contactResponse: 'contact=x&hash=y' });
    expect(await platform.shareContact()).toBe('contact=x&hash=y');
    expect(telegram.callsOf('web_app_request_phone')).toHaveLength(1);
    expect(telegram.callsOf('web_app_invoke_custom_method').map((p) => p?.method)).toContain(
      'getRequestedContact',
    );

    expect(await createMockPlatform({ contact: false }).platform.shareContact()).toBeNull();
    expect(await createMockPlatform({ version: '6.0' }).platform.shareContact()).toBeNull();
  });

  it('старый клиент: метода нет — фолбэк без вызова', async () => {
    const { platform, telegram } = createMockPlatform({ version: '6.0' });
    expect(await platform.requestContact()).toBe(false);
    expect(await platform.location.request()).toBeNull();
    platform.haptics.impact('light');
    platform.setClosingConfirmation(true);
    expect(telegram.callsOf('web_app_trigger_haptic_feedback')).toEqual([]);
    expect(telegram.callsOf('web_app_setup_closing_behavior')).toEqual([]);
  });

  it('haptics, closing confirmation, вертикальные свайпы', () => {
    const { platform, telegram } = createMockPlatform();
    platform.haptics.notification('success');
    platform.setClosingConfirmation(true);
    platform.setVerticalSwipes(false);
    expect(telegram.callsOf('web_app_trigger_haptic_feedback')).toEqual([
      { type: 'notification', notification_type: 'success' },
    ]);
    expect(telegram.callsOf('web_app_setup_closing_behavior')).toEqual([
      { need_confirmation: true },
    ]);
    expect(telegram.callsOf('web_app_setup_swipe_behavior')).toEqual([
      { allow_vertical_swipe: false },
    ]);
  });

  it('LocationManager', async () => {
    expect(await createMockPlatform().platform.location.request()).toEqual({
      latitude: 45.2671,
      longitude: 19.8335,
    });
    expect(await createMockPlatform({ location: null }).platform.location.request()).toBeNull();
  });

  it('ссылки', async () => {
    const { platform, telegram } = createMockPlatform();
    platform.openTelegramLink('https://t.me/sosed_rs_bot?startapp=h');
    platform.openLink('https://example.org/terms');
    expect(await platform.shareLink('https://t.me/sosed_rs_bot?startapp=h', 'Заявка')).toBe(
      'shared',
    );
    expect(telegram.callsOf('web_app_open_tg_link')[0]).toEqual({
      path_full: '/sosed_rs_bot?startapp=h',
    });
    expect(telegram.callsOf('web_app_open_link')).toEqual([{ url: 'https://example.org/terms' }]);
    expect(String(telegram.callsOf('web_app_open_tg_link')[1]?.path_full)).toMatch(
      /^\/share\/url\?url=/,
    );
  });
});

describe('хранилища', () => {
  it('DeviceStorage с Bot API 9.0', async () => {
    const { platform, telegram } = createMockPlatform({ version: '9.0' });
    await platform.storage.device.set('draft', '{"step":2}');
    expect(await platform.storage.device.get('draft')).toBe('{"step":2}');
    await platform.storage.device.remove('draft');
    expect(await platform.storage.device.get('draft')).toBeNull();
    expect(telegram.callsOf('web_app_device_storage_save_key').length).toBe(2);
  });

  it('до 9.0 device — это CloudStorage', async () => {
    const { platform, telegram } = createMockPlatform({ version: '8.0' });
    await platform.storage.device.set('draft', 'x');
    expect(await platform.storage.device.get('draft')).toBe('x');
    expect(telegram.callsOf('web_app_device_storage_save_key')).toEqual([]);
    expect(telegram.callsOf('web_app_invoke_custom_method').map((p) => p?.method)).toEqual([
      'saveStorageValue',
      'getStorageValues',
    ]);
  });
});
