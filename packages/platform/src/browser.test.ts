import { describe, expect, it, vi } from 'vitest';

import { createBrowserPlatform } from './browser.ts';
import { compareVersions, isVersionAtLeast } from './version.ts';

describe('браузер', () => {
  it('кнопки рисуются в контенте; нажатие — только у видимой активной', () => {
    const platform = createBrowserPlatform();
    expect(platform.mainButton.native).toBe(false);
    const clicks: number[] = [];
    platform.mainButton.onClick(() => clicks.push(1));
    platform.mainButton.click();
    platform.mainButton.set({ text: 'Далее', visible: true, enabled: false });
    platform.mainButton.click();
    platform.mainButton.set({ enabled: true });
    platform.mainButton.click();
    expect(clicks).toEqual([1]);
  });

  it('«Назад» — в контенте: историю браузера не трогает', () => {
    const platform = createBrowserPlatform();
    const push = vi.spyOn(window.history, 'pushState');
    const clicks: number[] = [];
    platform.backButton.onClick(() => clicks.push(1));
    platform.backButton.setVisible(true);
    expect(platform.backButton.native).toBe(false);
    expect(push).not.toHaveBeenCalled();
    // «назад» браузера ведёт роутер по истории, а не обработчик экрана
    window.dispatchEvent(new PopStateEvent('popstate'));
    expect(clicks).toEqual([]);
  });

  it('хранилище — localStorage с префиксом', async () => {
    const platform = createBrowserPlatform();
    await platform.storage.device.set('draft', 'x');
    expect(window.localStorage.getItem('sosed:draft')).toBe('x');
    expect(await platform.storage.device.get('draft')).toBe('x');
    await platform.storage.device.remove('draft');
    expect(await platform.storage.device.get('draft')).toBeNull();
  });

  it('поделиться: navigator.share, иначе копирование', async () => {
    const platform = createBrowserPlatform();
    const writeText = vi.fn(async () => {});
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
    expect(await platform.shareLink('https://example.org/j/1')).toBe('copied');
    expect(writeText).toHaveBeenCalledWith('https://example.org/j/1');
    const share = vi.fn(async () => {});
    Object.defineProperty(navigator, 'share', { value: share, configurable: true });
    expect(await platform.shareLink('https://example.org/j/1', 'Заявка')).toBe('shared');
  });

  it('startapp из адреса и возможности Telegram выключены', () => {
    window.history.replaceState(null, '', '/?startapp=s_abc');
    const platform = createBrowserPlatform();
    expect(platform.launch.startParam).toBe('s_abc');
    expect(platform.capabilities.secondaryButton).toBe(false);
    expect(platform.launch.rawInitData).toBeNull();
  });
});

describe('версии', () => {
  it('7.10 новее 7.9', () => {
    expect(compareVersions('7.10', '7.9')).toBe(1);
    expect(isVersionAtLeast('9.0', '9')).toBe(true);
    expect(isVersionAtLeast('6.9', '7.0')).toBe(false);
  });
});
