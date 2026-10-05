// Черновик мастера S20a–d в памяти и в хранилище платформы (DeviceStorage Telegram, в браузере —
// localStorage): шаги правят один черновик, запись — с задержкой ввода, при входе в мастер он
// поднимается из хранилища — так «черновик сохраняется сам» и переживает закрытие Mini App. После
// публикации стирается. Ключ публикации — один на тело заявки: сервер ответил, что ключ потрачен
// на другое тело (черновик поправили после публикации, которая выглядела неудачной), — черновик
// получает новый (`rekey`). Правка своей заявки (`?edit=<id>`, S23 «Изменить», 5.6) — тот же
// мастер с черновиком из заявки: он живёт только в памяти и не трогает черновик новой заявки.
import type { JobOut } from '@sosed/api-client';
import type { DraftLanguage, JobDraft } from '@sosed/hooks';
import { DRAFT_STORAGE_KEY, draftOfJob, newDraft, parseDraft, useJob } from '@sosed/hooks';
import type { Locale } from '@sosed/i18n';
import { useLocale } from '@sosed/i18n';
import type { KeyValueStorage } from '@sosed/platform';
import { usePlatform } from '@sosed/platform';
import { useSearch } from '@tanstack/react-router';
import { useEffect } from 'react';
import { create } from 'zustand';

import type { EditSearch } from './paths.ts';

/** Не чаще: ввод текста не пишет в DeviceStorage на каждую букву. */
const SAVE_DELAY_MS = 400;

export interface Editing {
  jobId: string;
  /** Версия заявки, с которой начали правку: If-Match сохранения. */
  version: number;
  /** Заявка, с которой начали правку: версия ушла вперёд — по ней видно, правили ли её где-то ещё. */
  base: JobOut;
}

interface DraftState {
  /** null — ещё не поднят из хранилища. */
  draft: JobDraft | null;
  storage: KeyValueStorage | null;
  /** Правится своя заявка; null — новая. */
  editing: Editing | null;
  start: (storage: KeyValueStorage, draft: JobDraft) => void;
  patch: (patch: Partial<JobDraft>) => void;
  /** Новый ключ публикации: старый уже потрачен на другое тело. */
  rekey: () => string;
  /** Опубликовано: черновик больше не нужен. */
  clear: () => Promise<void>;
  /** «Изменить» на S23: черновик — из заявки. */
  edit: (job: JobOut) => void;
  /** Правку сохранили или бросили: мастер снова — для новой заявки. */
  endEdit: () => void;
}

let timer: ReturnType<typeof setTimeout> | null = null;

export const useDraftStore = create<DraftState>((set, get) => ({
  draft: null,
  storage: null,
  editing: null,
  start: (storage, draft) => set({ storage, draft, editing: null }),
  patch: (patch) => {
    const { draft, storage, editing } = get();
    if (!draft) return;
    const next = { ...draft, ...patch, savedAt: new Date().toISOString() };
    set({ draft: next });
    if (editing) return; // правка живёт в памяти: черновик новой заявки в хранилище не трогаем
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => {
      timer = null;
      void storage?.set(DRAFT_STORAGE_KEY, JSON.stringify(next)).catch(() => undefined);
    }, SAVE_DELAY_MS);
  },
  rekey: () => {
    const key = crypto.randomUUID();
    get().patch({ key });
    return key;
  },
  clear: async () => {
    if (timer) clearTimeout(timer);
    timer = null;
    const { storage } = get();
    set({ draft: null });
    await storage?.remove(DRAFT_STORAGE_KEY).catch(() => undefined);
  },
  edit: (job) => {
    if (timer) clearTimeout(timer);
    timer = null;
    set({
      draft: draftOfJob(job, new Date()),
      editing: { jobId: job.id, version: job.version, base: job },
    });
  },
  endEdit: () => set({ draft: null, editing: null }),
}));

/** Язык общения нового черновика — язык интерфейса. */
const languageOf = (locale: Locale): DraftLanguage[] => [locale === 'ru' ? 'ru' : 'sr'];

/**
 * Черновик для шага мастера. Первый вход в сессии поднимает его из хранилища (или начинает
 * новый); с `?edit=<id>` — из своей заявки; null — пока поднимается.
 */
export function useJobDraft() {
  const platform = usePlatform();
  const locale = useLocale();
  const search: EditSearch = useSearch({ strict: false });
  const editId = search.edit ?? null;
  const job = useJob(editId);
  const draft = useDraftStore((state) => state.draft);
  const patch = useDraftStore((state) => state.patch);
  const editing = useDraftStore((state) => state.editing);
  useEffect(() => {
    const state = useDraftStore.getState();
    if (editId) {
      if (state.editing?.jobId !== editId && job.data?.viewer_role === 'owner') {
        state.edit(job.data);
      }
      return;
    }
    if (state.editing) state.endEdit();
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
  }, [platform, locale, editId, job.data]);
  // правка: чужой черновик (новой заявки) до загрузки заявки не показываем
  const ready = editId ? (editing?.jobId === editId ? draft : null) : editing ? null : draft;
  return { draft: ready, patch, editing: editId ? editing : null };
}
