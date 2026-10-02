// Черновик мастера S20a–d в памяти и в хранилище платформы (DeviceStorage Telegram, в браузере —
// localStorage): шаги правят один черновик, запись — с задержкой ввода, при входе в мастер он
// поднимается из хранилища — так «черновик сохраняется сам» и переживает закрытие Mini App. После
// публикации стирается.
import type { DraftLanguage, JobDraft } from '@sosed/hooks';
import { DRAFT_STORAGE_KEY, newDraft, parseDraft } from '@sosed/hooks';
import type { Locale } from '@sosed/i18n';
import { useLocale } from '@sosed/i18n';
import type { KeyValueStorage } from '@sosed/platform';
import { usePlatform } from '@sosed/platform';
import { useEffect } from 'react';
import { create } from 'zustand';

/** Не чаще: ввод текста не пишет в DeviceStorage на каждую букву. */
const SAVE_DELAY_MS = 400;

interface DraftState {
  /** null — ещё не поднят из хранилища. */
  draft: JobDraft | null;
  storage: KeyValueStorage | null;
  start: (storage: KeyValueStorage, draft: JobDraft) => void;
  patch: (patch: Partial<JobDraft>) => void;
  /** Опубликовано: черновик больше не нужен. */
  clear: () => Promise<void>;
}

let timer: ReturnType<typeof setTimeout> | null = null;

export const useDraftStore = create<DraftState>((set, get) => ({
  draft: null,
  storage: null,
  start: (storage, draft) => set({ storage, draft }),
  patch: (patch) => {
    const { draft, storage } = get();
    if (!draft) return;
    const next = { ...draft, ...patch, savedAt: new Date().toISOString() };
    set({ draft: next });
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => {
      timer = null;
      void storage?.set(DRAFT_STORAGE_KEY, JSON.stringify(next)).catch(() => undefined);
    }, SAVE_DELAY_MS);
  },
  clear: async () => {
    if (timer) clearTimeout(timer);
    timer = null;
    const { storage } = get();
    set({ draft: null });
    await storage?.remove(DRAFT_STORAGE_KEY).catch(() => undefined);
  },
}));

/** Язык общения нового черновика — язык интерфейса. */
const languageOf = (locale: Locale): DraftLanguage[] => [locale === 'ru' ? 'ru' : 'sr'];

/**
 * Черновик для шага мастера. Первый вход в сессии поднимает его из хранилища (или начинает
 * новый); null — пока поднимается.
 */
export function useJobDraft() {
  const platform = usePlatform();
  const locale = useLocale();
  const draft = useDraftStore((state) => state.draft);
  const patch = useDraftStore((state) => state.patch);
  useEffect(() => {
    if (useDraftStore.getState().draft) return;
    let alive = true;
    const storage = platform.storage.device;
    void storage
      .get(DRAFT_STORAGE_KEY)
      .catch(() => null)
      .then((raw) => {
        if (!alive || useDraftStore.getState().draft) return;
        const now = new Date();
        const saved = parseDraft(raw, now);
        useDraftStore
          .getState()
          .start(storage, saved ?? newDraft(crypto.randomUUID(), now, languageOf(locale)));
      });
    return () => {
      alive = false;
    };
  }, [platform, locale]);
  return { draft, patch };
}
