// platform.location.get(): LocationManager Telegram, фолбэк старых клиентов и браузер.
import { afterEach, describe, expect, it, vi } from 'vitest';

import { createBrowserPlatform } from './browser.ts';
import { LOCATION_TIMEOUT_MS } from './location.ts';
import { MOCK_LOCATION, createMockPlatform } from './mock.ts';

type Success = (position: { coords: { latitude: number; longitude: number } }) => void;

/** navigator.geolocation устройства: точка, отказ или нет API вовсе. */
function stubGeolocation(answer: { lat: number; lon: number } | 'denied' | 'missing') {
  const getCurrentPosition = vi.fn((success: Success, failure: () => void, _options?: object) => {
    if (answer === 'denied') failure();
    else if (answer !== 'missing') {
      success({ coords: { latitude: answer.lat, longitude: answer.lon } });
    }
  });
  vi.stubGlobal('navigator', {
    ...navigator,
    geolocation: answer === 'missing' ? undefined : { getCurrentPosition },
  });
  return getCurrentPosition;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('location.get в Telegram', () => {
  it('LocationManager: точка mock-клиента — в Лимане', async () => {
    const { platform, telegram } = createMockPlatform();
    expect(await platform.location.get()).toEqual({
      lat: MOCK_LOCATION.latitude,
      lon: MOCK_LOCATION.longitude,
    });
    expect(telegram.callsOf('web_app_check_location')).toHaveLength(1);
    expect(telegram.callsOf('web_app_request_location')).toHaveLength(1);
  });

  it('отказ или нет геолокации — null, геолокацию WebView не спрашиваем', async () => {
    const browser = stubGeolocation({ lat: 1, lon: 2 });
    expect(await createMockPlatform({ location: null }).platform.location.get()).toBeNull();
    expect(browser).not.toHaveBeenCalled();
  });

  it('старый клиент без LocationManager — геолокация WebView', async () => {
    const browser = stubGeolocation({ lat: 45.25, lon: 19.84 });
    const { platform, telegram } = createMockPlatform({ version: '7.10' });
    expect(await platform.location.get()).toEqual({ lat: 45.25, lon: 19.84 });
    expect(telegram.callsOf('web_app_check_location')).toEqual([]);
    expect(browser).toHaveBeenCalledOnce();
  });

  it('старый клиент, а у WebView геолокации нет — null', async () => {
    stubGeolocation('missing');
    expect(await createMockPlatform({ version: '6.0' }).platform.location.get()).toBeNull();
  });
});

describe('location.get в браузере', () => {
  it('точка без высокой точности и с тайм-аутом', async () => {
    const browser = stubGeolocation({ lat: 45.2397, lon: 19.835 });
    expect(await createBrowserPlatform().location.get()).toEqual({ lat: 45.2397, lon: 19.835 });
    expect(browser.mock.calls[0]?.[2]).toMatchObject({
      enableHighAccuracy: false,
      timeout: LOCATION_TIMEOUT_MS,
    });
  });

  it('отказ и нет API — null', async () => {
    stubGeolocation('denied');
    expect(await createBrowserPlatform().location.get()).toBeNull();
    stubGeolocation('missing');
    expect(await createBrowserPlatform().location.get()).toBeNull();
  });
});
