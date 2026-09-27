// UI-состояние онбординга: выбор живёт, пока человек ходит между шагами и в правила S48 и обратно.
// На сервер уходит по MainButton каждого шага; после онбординга черновик сбрасывается.
import type { UserIntent } from '@sosed/api-client';
import { create } from 'zustand';

interface OnboardingDraft {
  /** Город S02a; null — ещё не выбран (по умолчанию — пилотный). */
  cityId: number | null;
  /** Намерение S02b; null — по умолчанию «Найти мастера», как на артборде. */
  intent: UserIntent | null;
  /** Галочка S02c «18+ и правила»: согласие — только явное действие, сначала снята. */
  accepted: boolean;
  /** «Уведомления от бота» S02c: включены, как на артборде, — Telegram всё равно спросит. */
  notify: boolean;
  /** Галочку пытались пропустить: показать ошибку до следующего нажатия. */
  acceptMissing: boolean;
  set: (patch: Partial<Omit<OnboardingDraft, 'set' | 'reset'>>) => void;
  reset: () => void;
}

const INITIAL = {
  cityId: null,
  intent: null,
  accepted: false,
  notify: true,
  acceptMissing: false,
} as const;

export const useOnboardingStore = create<OnboardingDraft>((set) => ({
  ...INITIAL,
  set: (patch) => set(patch),
  reset: () => set(INITIAL),
}));
