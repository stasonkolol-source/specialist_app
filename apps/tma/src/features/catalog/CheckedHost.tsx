// Шторка «Что проверено» у точки сборки: экраны S08, S11 и S24 открывают её через openChecked
// (@sosed/hooks), а сама она — своим чанком при первом открытии, как шторка жалобы (ReportHost):
// в первый экран не попадает. Чанк не скачался без сети — NetworkError: экран ошибки покажет
// «Нет соединения».
import { NetworkError } from '@sosed/api-client';
import { closeChecked, useCheckedTarget } from '@sosed/hooks';
import { Suspense, lazy } from 'react';

const CheckedSheet = lazy(() =>
  import('./s08-profile/CheckedSheet.tsx').then(
    (module) => ({ default: module.CheckedSheet }),
    (error: unknown) => {
      closeChecked();
      throw navigator.onLine ? error : new NetworkError('checked chunk failed', { cause: error });
    },
  ),
);

export function CheckedHost() {
  const target = useCheckedTarget();
  if (!target) return null;
  return (
    <Suspense fallback={null}>
      <CheckedSheet key={target.kind} target={target} onClose={closeChecked} />
    </Suspense>
  );
}
