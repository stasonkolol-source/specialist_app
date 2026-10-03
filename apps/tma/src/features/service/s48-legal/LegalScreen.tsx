// Маршрут S48 `/legal/$document`: документ — параметр пути (deep link, S02c и S31 ведут на нужный),
// переключатель меняет его без новой записи в истории. «Назад» — нативная кнопка Telegram: на
// предыдущий экран, а без истории (открыли по ссылке) — в профиль, откуда S48 открывают.
import type { LegalDocumentKey } from '@sosed/hooks';
import { isLegalDocument } from '@sosed/hooks';
import { useBackButton } from '@sosed/platform';
import { Navigate, useParams, useRouter } from '@tanstack/react-router';

import { LegalView } from './LegalView.tsx';
import { LEGAL_PATH } from './paths.ts';
const FALLBACK_PATH = '/profile';

export function LegalScreen() {
  const router = useRouter();
  const { document } = useParams({ strict: false });
  useBackButton(() => {
    if (router.history.canGoBack()) router.history.back();
    else void router.navigate({ to: FALLBACK_PATH, replace: true });
  });
  if (!isLegalDocument(document)) {
    return <Navigate to={LEGAL_PATH} params={{ document: 'terms' }} replace />;
  }
  const open = (next: LegalDocumentKey) =>
    void router.navigate({ to: LEGAL_PATH, params: { document: next }, replace: true });
  return <LegalView document={document} onDocumentChange={open} />;
}
