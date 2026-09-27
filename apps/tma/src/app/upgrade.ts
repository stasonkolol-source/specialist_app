// Ответ 426 от любого запроса: версия Mini App ниже минимальной (X-Client) — экран обновления
// поверх всего приложения. Решение по client-config при старте принимает StartupGate.
import type { UpdateNeeded } from '@sosed/hooks';
import { create } from 'zustand';

interface UpgradeState {
  forced: UpdateNeeded;
  force: (kind: Exclude<UpdateNeeded, null>) => void;
}

export const useUpgradeStore = create<UpgradeState>((set) => ({
  forced: null,
  force: (kind) => set({ forced: kind }),
}));
