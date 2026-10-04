// Веб-ссылка на карточку специалиста `/s/<id>` и заявку `/j/<id>` (8.1, ARCHITECTURE §11.4): вне
// Telegram — «Открыть в Telegram» с кодом startapp сущности или «Продолжить в браузере» — гостевой
// просмотр S08 или S15. Внутри Telegram такой адрес сразу открывает экран. Битая ссылка — только
// «Открыть в Telegram» на главную.
import { useTranslation } from '@sosed/i18n';
import { usePlatform } from '@sosed/platform';
import { Navigate, useParams, useRouter } from '@tanstack/react-router';

import { OpenInTelegram } from './OpenInTelegram.tsx';
import type { WebEntity } from './links.ts';
import { ENTITY_PATHS, entityId, entityStart } from './links.ts';

/** Код startapp главной (packages/links). */
const HOME_START = 'h';

export function SpecialistLinkScreen() {
  return <EntityLink type="specialist" />;
}

export function JobLinkScreen() {
  return <EntityLink type="job" />;
}

function EntityLink({ type }: { type: WebEntity }) {
  const { t } = useTranslation('web');
  const { code = '' } = useParams({ strict: false }) as { code?: string };
  const router = useRouter();
  const platform = usePlatform();
  const id = entityId(code);
  if (id === null) return <OpenInTelegram start={HOME_START} />;
  const target = ENTITY_PATHS[type](id);
  if (platform.kind !== 'browser') return <Navigate to={target} replace />;
  return (
    <OpenInTelegram
      start={entityStart(type, id)}
      title={t(`link.${type}`)}
      onContinue={() => void router.navigate({ to: target })}
    />
  );
}
