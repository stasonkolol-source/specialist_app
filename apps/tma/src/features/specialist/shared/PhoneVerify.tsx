// «Подтвердить телефон» (решение владельца 2026-10-14: до беты, без лишних шагов): одна
// необязательная строка в кабинете S33 (блок «Доверие») и на S32c перед «Отправить на проверку».
// Нажатие — Telegram спрашивает номер (requestContact), backend ставит бейдж «Телефон подтверждён»
// (POST /me/phone); сам номер клиентам не показываем нигде. Подтверждён — строка-факт вместо кнопки.
// Клиент не умеет отдать контакт (браузер, старый Telegram) — строки нет: обещать нечего.
// Отказ и «номер уже в другом аккаунте» (409) — честным текстом под строкой.
import { ApiError, useIdentityGetMe } from '@sosed/api-client';
import { PhoneDeclinedError, useVerifyPhone } from '@sosed/hooks';
import { useTranslation } from '@sosed/i18n';
import { usePlatform } from '@sosed/platform';
import { Group, Row, SectionTitle } from '@sosed/ui-web';
import { useId } from 'react';

export function PhoneVerify({ titled = false }: { titled?: boolean }) {
  const { t } = useTranslation('specialist');
  const platform = usePlatform();
  const me = useIdentityGetMe();
  const { available, verify } = useVerifyPhone(platform);
  const titleId = useId();
  if (!me.data || (!me.data.phone_verified && !available)) return null;
  const confirm = () => {
    if (verify.isPending) return;
    verify.mutate(undefined, { onSuccess: () => platform.haptics.notification('success') });
  };
  const error = verify.error;
  const problem = error instanceof ApiError && error.status < 500 ? error.problem.detail : null;
  const body = (
    <>
      <div aria-live="polite">
        <Group>
          {me.data.phone_verified ? (
            <Row icon="shield" title={t('phone.verified')} />
          ) : (
            <Row
              icon="phone"
              title={t('phone.verify')}
              subtitle={t('phone.verifyHint')}
              chevron
              onClick={confirm}
            />
          )}
        </Group>
      </div>
      {error instanceof PhoneDeclinedError ? (
        <p role="status" className="m-0 px-1 text-cap text-text2">
          {t('phone.declined')}
        </p>
      ) : (
        error && (
          <p role="alert" className="m-0 px-1 text-cap text-danger">
            {problem ?? t('phone.failed')}
          </p>
        )
      )}
    </>
  );
  if (!titled) return <div className="flex flex-col gap-2">{body}</div>;
  return (
    <section aria-labelledby={titleId} className="flex flex-col gap-2">
      <SectionTitle id={titleId}>{t('phone.title')}</SectionTitle>
      {body}
    </section>
  );
}
