// S02c «Правила площадки», шаг 3 из 3 (DEVELOPMENT_PLAN 1.5b, ADR-0018): четыре правила кратко и
// ссылка на полный текст S48. Одна галочка «18+ и правила» — POST /me/consents с версиями из
// client-config: без неё «Начать» не пускает. «Уведомления от бота» — requestWriteAccess клиента
// Telegram и, если разрешили, POST /me/telegram/write-access; отказ онбординг не останавливает.
// «Назад» — туда, откуда пришли; открыли шаг сразу при запуске — новому пользователю на S02b
// (недоделанный онбординг), вернувшемуся после новой редакции правил «Назад» не нужен. Тот же экран
// показывается перед создающим действием без согласия.
import {
  ApiError,
  notificationsGrantTelegramWriteAccess,
  useIdentityAcceptConsents,
  useIdentityGetMe,
} from '@sosed/api-client';
import { useClientConfig } from '@sosed/hooks';
import { useTranslation } from '@sosed/i18n';
import { useBackButton, usePlatform } from '@sosed/platform';
import { Checkbox, NumIcon, RowIcon, Switch } from '@sosed/ui-web';
import { useRouter } from '@tanstack/react-router';
import type { MouseEvent } from 'react';
import { useId, useRef, useState } from 'react';

import { SaveError } from '../shared/SaveError.tsx';
import { StepHeader } from '../shared/StepHeader.tsx';
import { useOnboardingFlow, useStepButton } from '../shared/flow.ts';
import { useOnboardingStore } from '../shared/store.ts';

/** S48, правила площадки (маршрут features/service/s48-legal). */
const LEGAL_PATH = '/legal/$document';
const RULES_HREF = '/legal/terms';

const RULES = ['polite', 'contacts', 'payment', 'reviews'] as const;

export function RulesScreen() {
  const { t } = useTranslation('onboarding');
  const platform = usePlatform();
  const router = useRouter();
  const flow = useOnboardingFlow();
  const config = useClientConfig();
  const me = useIdentityGetMe();
  const { accepted, notify, acceptMissing, set } = useOnboardingStore();
  const checkbox = useRef<HTMLButtonElement>(null);
  const [problem, setProblem] = useState<'outdated' | 'unavailable' | null>(null);
  const canNotify = platform.capabilities.requestWriteAccess;
  // согласий ещё не было — онбординг нового пользователя, а не новая редакция правил
  const firstTime = me.data !== undefined && Object.keys(me.data.consents).length === 0;

  // Разрешение писать — после согласия: пока клиент Telegram спрашивает, MainButton в ожидании
  const allowNotifications = async () => {
    if (!notify || !canNotify) return;
    const allowed = await platform.requestWriteAccess().catch(() => false);
    if (allowed) await notificationsGrantTelegramWriteAccess().catch(() => undefined);
  };

  const consents = useIdentityAcceptConsents({
    mutation: {
      onSuccess: async (next) => {
        await allowNotifications();
        // впервые (согласий не было) специалиста ведём в мастер профиля, вернувшегося — домой
        flow.saved('rules', next, firstTime);
      },
      onError: (error) => {
        // редакция сменилась, пока экран был открыт: новый текст — и галочка заново
        if (error instanceof ApiError && error.code === 'legal_version_outdated') {
          setProblem('outdated');
          set({ accepted: false });
          void config.refetch();
        }
      },
    },
  });

  const start = () => {
    if (consents.isPending) return;
    if (!accepted) {
      set({ acceptMissing: true });
      platform.haptics.notification('error');
      checkbox.current?.focus();
      return;
    }
    const versions = config.data?.legal_versions;
    if (!versions?.terms || !versions.privacy) {
      setProblem('unavailable');
      void config.refetch();
      return;
    }
    setProblem(null);
    consents.mutate({
      data: { terms_version: versions.terms, privacy_version: versions.privacy },
    });
  };
  useStepButton({ text: t('rules.start'), onClick: start, loading: consents.isPending });
  // Открыли шаг сразу при запуске: новому пользователю (согласий ещё не было) «Назад» — на S02b,
  // как S02b ведёт на S02a; после новой редакции правил «Назад» не нужен — в шапке «Закрыть»
  useBackButton(router.history.canGoBack() || firstTime ? () => flow.back('intent') : null);

  const openRules = (event: MouseEvent<HTMLAnchorElement>) => {
    event.preventDefault();
    void router.navigate({ to: LEGAL_PATH, params: { document: 'terms' } });
  };

  const errorId = useId();
  const notifyTitle = useId();
  return (
    <section className="flex flex-col gap-4 px-4 pt-4 pb-6">
      <StepHeader step={3} title={t('rules.title')} />

      <ol className="m-0 flex list-none flex-col gap-3.5 rounded-card bg-surface p-4">
        {RULES.map((rule, index) => (
          <li key={rule} className="flex items-start gap-3">
            <span aria-hidden="true">
              <NumIcon>{index + 1}</NumIcon>
            </span>
            <span className="text-sm">
              <b className="font-semibold">{t(`rules.${rule}.lead`)}</b> {t(`rules.${rule}.text`)}
            </span>
          </li>
        ))}
        <li>
          <a
            href={router.history.createHref(RULES_HREF)}
            onClick={openRules}
            className="flex min-h-11 items-center text-sm font-semibold text-accent"
          >
            {t('rules.readAll')}
          </a>
        </li>
      </ol>

      <div className="flex flex-col gap-2">
        <Checkbox
          ref={checkbox}
          checked={accepted}
          onChange={(next) => set({ accepted: next, acceptMissing: false })}
          invalid={acceptMissing && !accepted}
          describedBy={acceptMissing && !accepted ? errorId : undefined}
          className="rounded-card bg-surface p-4"
        >
          {t('rules.accept')}
        </Checkbox>
        {acceptMissing && !accepted && (
          <p id={errorId} role="alert" className="m-0 px-4 text-sm text-danger">
            {t('rules.acceptRequired')}
          </p>
        )}
      </div>

      {canNotify && (
        <section
          aria-labelledby={notifyTitle}
          className="flex items-start gap-3 rounded-card bg-surface p-4"
        >
          <RowIcon icon="bell" />
          <span className="flex min-w-0 flex-1 flex-col gap-1">
            <span id={notifyTitle} className="font-semibold">
              {t('rules.notifications.title')}
            </span>
            <span className="text-sm text-text2">{t('rules.notifications.text')}</span>
          </span>
          <Switch
            checked={notify}
            onChange={(next) => set({ notify: next })}
            label={t('rules.notifications.title')}
          />
        </section>
      )}

      {problem && <SaveError error={null} message={t(`rules.${problem}`)} />}
      {consents.isError && !problem && <SaveError error={consents.error} />}
    </section>
  );
}
