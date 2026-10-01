// Несохранённый ввод шагов S32b–c: живёт, пока человек ходит между шагами и уходит из мастера.
// На сервер уходит по MainButton каждого шага — так черновик и «сохраняется сам»; после отправки на
// проверку сбрасывается. null — поле не трогали: экран показывает значение из профиля.
import type { Language, WorkMode } from '@sosed/api-client';
import { create } from 'zustand';

export type Radius = 3 | 5 | 10;

export interface BecomeDraft {
  categoryIds: number[] | null;
  headline: string | null;
  about: string | null;
  languages: Language[] | null;
  districtIds: number[] | null;
  workModes: WorkMode[] | null;
  radius: Radius | null;
  serviceTitle: string | null;
  /** Цена первой позиции в динарах — цифры, как введены. */
  servicePrice: string | null;
}

interface BecomeStore extends BecomeDraft {
  set: (patch: Partial<BecomeDraft>) => void;
  reset: () => void;
}

const INITIAL: BecomeDraft = {
  categoryIds: null,
  headline: null,
  about: null,
  languages: null,
  districtIds: null,
  workModes: null,
  radius: null,
  serviceTitle: null,
  servicePrice: null,
};

export const useBecomeStore = create<BecomeStore>((set) => ({
  ...INITIAL,
  set: (patch) => set(patch),
  reset: () => set(INITIAL),
}));
