// Версии Bot API: с какой версии клиент умеет метод. Методы новее SDK вызываются через postEvent.
import type { Capabilities } from './types.ts';

export function compareVersions(a: string, b: string): number {
  const pa = a.split('.').map(Number);
  const pb = b.split('.').map(Number);
  for (let i = 0; i < Math.max(pa.length, pb.length); i += 1) {
    const diff = (pa[i] ?? 0) - (pb[i] ?? 0);
    if (diff !== 0) return Math.sign(diff);
  }
  return 0;
}

export function isVersionAtLeast(current: string, required: string): boolean {
  return compareVersions(current, required) >= 0;
}

/** Минимальная версия Bot API для возможностей (core.telegram.org/bots/webapps). */
export const MIN_VERSION: Record<keyof Capabilities, string> = {
  haptics: '6.1',
  popup: '6.2',
  closingConfirmation: '6.2',
  cloudStorage: '6.9',
  requestContact: '6.9',
  requestWriteAccess: '6.9',
  verticalSwipes: '7.7',
  secondaryButton: '7.10',
  bottomBarColor: '7.10',
  safeArea: '8.0',
  location: '8.0',
  shareMessage: '8.0',
  deviceStorage: '9.0',
};

export function capabilitiesFor(version: string): Capabilities {
  return Object.fromEntries(
    Object.entries(MIN_VERSION).map(([name, min]) => [name, isVersionAtLeast(version, min)]),
  ) as unknown as Capabilities;
}
