// Публичные справочники запуска — между запусками Mini App: client-config, города и разделы
// каталога. Ничего личного: ни /me, ни своих списков, ни токенов — только ответы, одинаковые для
// всех. Повторный запуск поднимает их до первого кадра со временем их ответа: StartupGate не ждёт
// конфиг, плитки Главной видны сразу, а устаревшее перечитывается в фоне (startup.ts). Хранится
// сутки и только для этой версии приложения; хранилище недоступно (приватный режим, квота) — без
// него, как раньше.
import type { ClientConfigOut } from '@sosed/api-client';
import { FLAGS, categoriesQueryKey, citiesQueryKey, clientConfigQueryOptions } from '@sosed/hooks';
import { LOCALES } from '@sosed/i18n';
import type { QueryClient, QueryKey } from '@tanstack/react-query';
import { hashKey } from '@tanstack/react-query';

const STORAGE_KEY = 'sosed:public-queries';
/** Формат записи: меняется — прежние записи не читаются. */
const SCHEMA = 1;
const TTL_MS = 24 * 60 * 60_000;

interface Saved {
  build: string;
  savedAt: number;
  queries: { queryKey: QueryKey; data: unknown; updatedAt: number }[];
}

/** Что можно хранить: конфиг и справочники на каждом языке (дерево разделов — без города). */
function publicKeys(): QueryKey[] {
  return [
    clientConfigQueryOptions().queryKey,
    ...LOCALES.flatMap((locale) => [citiesQueryKey(locale), categoriesQueryKey(locale)]),
  ];
}

const buildOf = (version: string) => `${version}:${SCHEMA}`;

/** Поднять сохранённое в кэш до первого кадра; чужая версия или старше суток — стереть. */
export function restorePublicQueries(client: QueryClient, version: string, now = Date.now()) {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return;
    const saved = JSON.parse(raw) as Saved;
    if (saved.build !== buildOf(version) || now - saved.savedAt > TTL_MS) {
      localStorage.removeItem(STORAGE_KEY);
      return;
    }
    const allowed = new Set(publicKeys().map(hashKey));
    for (const { queryKey, data, updatedAt } of saved.queries) {
      if (!allowed.has(hashKey(queryKey)) || data == null || now - updatedAt > TTL_MS) continue;
      // время ответа — настоящее: устаревшее экраны перечитают сразу, но уже не с пустого экрана
      if (client.getQueryData(queryKey) === undefined) {
        client.setQueryData(queryKey, data, { updatedAt });
      }
    }
  } catch {
    // хранилище недоступно или запись битая — загрузим заново
  }
}

/** Сохранять конфиг и справочники после каждого удачного ответа. */
export function persistPublicQueries(client: QueryClient, version: string): () => void {
  const keys = publicKeys();
  const allowed = new Set(keys.map(hashKey));
  const configHash = hashKey(clientConfigQueryOptions().queryKey);
  // конфиг во время техработ не храним: следующий запуск начинался бы с экрана техработ
  const keep = (queryKey: QueryKey, data: unknown) =>
    hashKey(queryKey) !== configHash || (data as ClientConfigOut).flags[FLAGS.maintenance] !== true;
  const save = () => {
    const queries = keys.flatMap((queryKey) => {
      const state = client.getQueryState(queryKey);
      return state?.status === 'success' && state.data !== undefined && keep(queryKey, state.data)
        ? [{ queryKey, data: state.data, updatedAt: state.dataUpdatedAt }]
        : [];
    });
    try {
      const saved: Saved = { build: buildOf(version), savedAt: Date.now(), queries };
      localStorage.setItem(STORAGE_KEY, JSON.stringify(saved));
    } catch {
      // квота или приватный режим — без сохранения
    }
  };
  return client.getQueryCache().subscribe((event) => {
    if (
      event.type === 'updated' &&
      event.action.type === 'success' &&
      allowed.has(event.query.queryHash)
    ) {
      save();
    }
  });
}
