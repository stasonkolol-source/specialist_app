// Шторка жалобы S46 у точки сборки (DEVELOPMENT_PLAN 4.7): экраны S08, S11, S15 и S30 открывают её
// через openReport (@sosed/hooks), а сама она — своим чанком при первом открытии: в первый экран
// не попадает. Чанк не скачался без сети — NetworkError: экран ошибки покажет «Нет соединения».
import { NetworkError } from '@sosed/api-client';
import { closeReport, useReportTarget } from '@sosed/hooks';
import { Suspense, lazy } from 'react';

const ReportSheet = lazy(() =>
  import('./s46-report/index.ts').then(
    (module) => ({ default: module.ReportSheet }),
    (error: unknown) => {
      closeReport();
      throw navigator.onLine ? error : new NetworkError('report chunk failed', { cause: error });
    },
  ),
);

export function ReportHost() {
  const target = useReportTarget();
  if (!target) return null;
  return (
    <Suspense fallback={null}>
      <ReportSheet key={`${target.type}:${target.id}`} target={target} onClose={closeReport} />
    </Suspense>
  );
}
