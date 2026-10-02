// Фича «Заявки» (SPEC §6): лента S13–S15 (5.3), создание S20a–d и S21 (5.2); отклики (5.5) и «Мои
// заявки» (5.6) — заглушками сегментов.
export type { FeedSearch } from './shared/feed.ts';
export { feedSearch } from './shared/feed.ts';
export type { CreateSearch, DoneSearch, JobSearch } from './shared/paths.ts';
export {
  CREATE_PATHS,
  JOBS_PATHS,
  createSearch,
  doneSearch,
  jobPath,
  jobSearch,
} from './shared/paths.ts';
