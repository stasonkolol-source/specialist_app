// Фича «Заявки» (SPEC §6): лента S13–S15 и сохранённые заявки S12 (5.3), создание S20a–d и S21
// (5.2), отклик S16, «Мои отклики» S17 и шаблоны откликов S57 (5.5); «Мои заявки» (5.6) — заглушкой
// сегмента.
export type { FeedSearch } from './shared/feed.ts';
export { feedSearch } from './shared/feed.ts';
export type {
  CreateSearch,
  DoneSearch,
  EditSearch,
  JobSearch,
  ResponsesSearch,
} from './shared/paths.ts';
export {
  CREATE_PATHS,
  JOBS_PATHS,
  SAVED_PATHS,
  createSearch,
  doneSearch,
  editSearch,
  dealPath,
  jobPath,
  jobSearch,
  respondPath,
  responsesSearch,
} from './shared/paths.ts';
