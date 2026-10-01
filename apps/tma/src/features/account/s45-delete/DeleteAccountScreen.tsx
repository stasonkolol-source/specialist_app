// S45 Удаление аккаунта (DEVELOPMENT_PLAN 2.12a, ARCHITECTURE §7.10): что удалится и что останется
// без имени, галочка «Понимаю» и MainButton цвета danger → POST /me/deletion. Через 7 дней аккаунт
// удалит задача identity.process_deletions; до этого здесь — дата и «Отменить удаление».
// «Нужна пауза?» ведёт к паузе профиля в S38 — только если профиль специалиста виден клиентам.
// Вход — строка «Удалить аккаунт» на S31 (с 4.9 — и из настроек S43).
import { useIdentityGetMe } from '@sosed/api-client';
import { tokens } from '@sosed/design-tokens';
import { useCancelDeletion, useMyProfile, useRequestDeletion } from '@sosed/hooks';
import { useFormat, useTranslation } from '@sosed/i18n';
import { useBackButton, useColorScheme, useMainButton, usePlatform } from '@sosed/platform';
import type { IconName } from '@sosed/ui-web';
import { Banner, Button, Checkbox, Heading, Icon, Skeleton, Text } from '@sosed/ui-web';
import { useRouter } from '@tanstack/react-router';
import type { ReactNode } from 'react';
import { useId, useRef, useState } from 'react';

import { ACCOUNT_PATHS } from '../paths.ts';

/** S31: сюда — «Назад» без истории и после отмены удаления. */
const ACCOUNT_PATH = ACCOUNT_PATHS.home;
/** S38 кабинета: пауза профиля. Фичи друг друга не импортируют — адрес строкой. */
const PAUSE_PATH = '/cabinet/availability';

const REMOVED = ['profile', 'messages', 'logins', 'reviews'] as const;
const KEPT = ['deals', 'law', 'hashes'] as const;

export function DeleteAccountScreen() {
  const { t } = useTranslation('service');
  const router = useRouter();
  const me = useIdentityGetMe();
  useBackButton(() => {
    if (router.history.canGoBack()) router.history.back();
    else void router.navigate({ to: ACCOUNT_PATH, replace: true });
  });

  if (me.data?.deletion_scheduled_at) {
    return <Scheduled at={new Date(me.data.deletion_scheduled_at)} />;
  }
  if (me.data) return <DeleteForm />;
  return (
    <section className="flex flex-col gap-3 px-4 pt-3 pb-6">
      <Heading variant="h2" as="h1">
        {t('deletion.title')}
      </Heading>
      <Skeleton className="h-40" radius="card" />
    </section>
  );
}

/** MainButton в цветах макета: удаление — danger, отмена — акцент. */
function useScreenButton(
  props: { text: string; onClick: () => void; loading?: boolean },
  tone: 'danger' | 'accent',
) {
  const palette = tokens.color[useColorScheme()];
  return useMainButton({
    ...props,
    color: palette[tone],
    textColor: palette[tone === 'danger' ? 'danger-ink' : 'accent-ink'],
  });
}

function DeleteForm() {
  const { t } = useTranslation('service');
  const router = useRouter();
  const platform = usePlatform();
  const profile = useMyProfile();
  const request = useRequestDeletion();
  const [understood, setUnderstood] = useState(false);
  const [checked, setChecked] = useState(false);
  const checkbox = useRef<HTMLButtonElement>(null);
  const errorId = useId();
  const visible = profile.data?.status === 'published' || profile.data?.status === 'hidden';

  useScreenButton(
    {
      text: t('deletion.submit'),
      loading: request.isPending,
      onClick: () => {
        if (request.isPending) return;
        if (!understood) {
          setChecked(true);
          platform.haptics.notification('error');
          checkbox.current?.focus();
          return;
        }
        request.mutate(undefined, {
          onSuccess: () => platform.haptics.notification('warning'),
        });
      },
    },
    'danger',
  );

  return (
    <section className="flex flex-col gap-3 px-4 pt-3 pb-6">
      <div className="flex flex-col gap-2">
        <Heading variant="h2" as="h1">
          {t('deletion.title')}
        </Heading>
        <Text variant="sm" secondary>
          {t('deletion.lead')}
        </Text>
      </div>
      {visible && (
        <Button variant="outline" full onClick={() => void router.navigate({ to: PAUSE_PATH })}>
          {t('deletion.pause')}
        </Button>
      )}
      <Section title={t('deletion.removedTitle')}>
        <List icon="x" tone="text-danger">
          {REMOVED.map((item) => t(`deletion.removed.${item}`))}
        </List>
      </Section>
      <Section title={t('deletion.keptTitle')}>
        <List icon="lock" tone="text-text2">
          {KEPT.map((item) => t(`deletion.kept.${item}`))}
        </List>
        <Text variant="cap">{t('deletion.keptNote')}</Text>
      </Section>
      <div className="flex flex-col gap-2">
        <Checkbox
          ref={checkbox}
          checked={understood}
          onChange={(next) => {
            setUnderstood(next);
            setChecked(false);
          }}
          invalid={checked && !understood}
          describedBy={checked && !understood ? errorId : undefined}
        >
          {t('deletion.confirm')}
        </Checkbox>
        {checked && !understood && (
          <p id={errorId} role="alert" className="m-0 text-sm text-danger">
            {t('deletion.confirmRequired')}
          </p>
        )}
      </div>
    </section>
  );
}

/** .card.tight с заголовком h3: секция «Удалится» и «Останется без вашего имени». */
function Section({ title, children }: { title: string; children: ReactNode }) {
  const id = useId();
  return (
    <section aria-labelledby={id} className="flex flex-col gap-2 rounded-card bg-surface p-4">
      <h2 id={id} className="m-0 text-h3">
        {title}
      </h2>
      {children}
    </section>
  );
}

function List({ icon, tone, children }: { icon: IconName; tone: string; children: string[] }) {
  return (
    <ul className="m-0 flex list-none flex-col gap-2 p-0 text-sm">
      {children.map((item) => (
        <li key={item} className="flex items-start gap-2.5">
          <Icon name={icon} size={16} className={`mt-0.5 ${tone}`} />
          {item}
        </li>
      ))}
    </ul>
  );
}

/** Запрос принят: дата удаления и отмена — MainButton. Отменили — обратно в профиль. */
function Scheduled({ at }: { at: Date }) {
  const { t } = useTranslation('service');
  const format = useFormat();
  const router = useRouter();
  const platform = usePlatform();
  const cancel = useCancelDeletion();

  useScreenButton(
    {
      text: t('deletion.cancel'),
      loading: cancel.isPending,
      onClick: () => {
        if (cancel.isPending) return;
        cancel.mutate(undefined, {
          onSuccess: () => {
            platform.haptics.notification('success');
            void router.navigate({ to: ACCOUNT_PATH, replace: true });
          },
        });
      },
    },
    'accent',
  );

  return (
    <section className="flex flex-col gap-3 px-4 pt-3 pb-6">
      <Heading variant="h2" as="h1">
        {t('deletion.title')}
      </Heading>
      <Banner tone="danger" role="status">
        <b className="font-semibold">{t('deletion.scheduled', { date: format.date(at) })}</b>
        <br />
        {t('deletion.scheduledText')}
      </Banner>
    </section>
  );
}
