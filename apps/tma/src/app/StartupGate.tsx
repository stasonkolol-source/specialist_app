// Client-config до маршрутов (DEVELOPMENT_PLAN 1.1): минимальные версии решают, пускать ли в
// приложение. Конфиг недоступен — пускаем: без сети экраны сами покажут S49a.
import { requiredUpdate, useClientConfig } from '@sosed/hooks';
import type { UpdateNeeded } from '@sosed/hooks';
import { useTranslation } from '@sosed/i18n';
import { usePlatform } from '@sosed/platform';
import { Button, EmptyState } from '@sosed/ui-web';
import type { ReactNode } from 'react';

import { useUpgradeStore } from './upgrade.ts';

export function StartupGate({ appVersion, children }: { appVersion: string; children: ReactNode }) {
  const platform = usePlatform();
  const config = useClientConfig();
  const forced = useUpgradeStore((state) => state.forced);
  if (config.isPending) return null;
  const telegram = platform.kind === 'browser' ? null : platform.launch.version;
  const need = forced ?? requiredUpdate(config.data, { app: appVersion, telegram });
  return need ? <UpdateScreen kind={need} /> : children;
}

function UpdateScreen({ kind }: { kind: Exclude<UpdateNeeded, null> }) {
  const { t } = useTranslation();
  return (
    <div className="flex min-h-dvh items-center justify-center bg-bg2">
      {kind === 'telegram' ? (
        <EmptyState icon="alert" title={t('update.telegramTitle')}>
          {t('update.telegramText')}
        </EmptyState>
      ) : (
        <EmptyState
          icon="refresh"
          title={t('update.appTitle')}
          action={<Button onClick={() => window.location.reload()}>{t('update.reload')}</Button>}
        >
          {t('update.appText')}
        </EmptyState>
      )}
    </div>
  );
}
