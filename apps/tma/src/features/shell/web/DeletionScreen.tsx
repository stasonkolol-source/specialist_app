// «Как удалить аккаунт» (8.1): статическая страница для Google Play — удаление по веб-ссылке, без
// входа на сайте. Аккаунт удаляется в Telegram: S45 в Mini App (Профиль → «Настройки» → «Удалить
// аккаунт») или кнопка «Удалить аккаунт» у /settings бота. Что удалится и что останется — те же
// строки, что на S45 (неймспейс account), чтобы страница не расходилась с экраном. Кнопка ведёт в
// Mini App сразу на S45 (`startapp=m_deletion`); без доступа к Telegram — поддержка.
import { useSupportLink } from '@sosed/hooks';
import { useTranslation } from '@sosed/i18n';
import { useBackButton } from '@sosed/platform';
import { Button, Card, Heading, Icon, NumIcon, Text } from '@sosed/ui-web';
import { useRouter } from '@tanstack/react-router';
import { useId } from 'react';

import { telegramLink } from './paths.ts';

const DELETION_START = 'm_deletion';
const APP_STEPS = ['open', 'settings', 'confirm'] as const;
const BOT_STEPS = ['command', 'button'] as const;
const REMOVED = ['profile', 'messages', 'logins', 'reviews'] as const;
const KEPT = ['deals', 'law', 'hashes'] as const;

export function DeletionScreen() {
  const { t } = useTranslation('web');
  const { t: account } = useTranslation('account');
  const router = useRouter();
  const support = useSupportLink();
  const href = telegramLink(DELETION_START);
  useBackButton(router.history.canGoBack() ? () => router.history.back() : null);

  return (
    <section className="flex flex-col gap-4 px-4 pt-3 pb-6">
      <Heading variant="h2" as="h1">
        {t('deletion.title')}
      </Heading>
      <Text secondary>{t('deletion.lead')}</Text>
      <Steps
        title={t('deletion.appTitle')}
        steps={APP_STEPS.map((step) => t(`deletion.app.${step}`))}
      />
      <Steps
        title={t('deletion.botTitle')}
        steps={BOT_STEPS.map((step) => t(`deletion.bot.${step}`))}
      />
      <Text variant="sm" secondary>
        {account('deletion.lead')}
      </Text>
      <Facts
        title={account('deletion.removedTitle')}
        icon="trash"
        items={REMOVED.map((key) => account(`deletion.removed.${key}`))}
      />
      <Facts
        title={account('deletion.keptTitle')}
        icon="lock"
        items={KEPT.map((key) => account(`deletion.kept.${key}`))}
        note={account('deletion.keptNote')}
      />
      <Text variant="sm" secondary>
        {t('deletion.support')}
      </Text>
      <div className="flex flex-col gap-3">
        {href && (
          <Button href={href} full icon="send">
            {t('deletion.open')}
          </Button>
        )}
        {support && (
          <Button href={support} variant="outline" full>
            {account('help.support')}
          </Button>
        )}
      </div>
    </section>
  );
}

function Steps({ title, steps }: { title: string; steps: readonly string[] }) {
  const titleId = useId();
  return (
    <Card as="section" tight aria-labelledby={titleId}>
      <Heading variant="h3" as="h2" id={titleId}>
        {title}
      </Heading>
      <ol className="m-0 flex list-none flex-col gap-2.5 p-0">
        {steps.map((step, index) => (
          <li key={step} className="flex items-center gap-3 text-sm">
            <NumIcon>{index + 1}</NumIcon>
            {step}
          </li>
        ))}
      </ol>
    </Card>
  );
}

function Facts({
  title,
  icon,
  items,
  note,
}: {
  title: string;
  icon: 'trash' | 'lock';
  items: readonly string[];
  note?: string;
}) {
  const titleId = useId();
  return (
    <Card as="section" tight aria-labelledby={titleId}>
      <Heading variant="h3" as="h2" id={titleId}>
        {title}
      </Heading>
      <ul className="m-0 flex list-none flex-col gap-2 p-0">
        {items.map((item) => (
          <li key={item} className="flex items-start gap-2.5 text-sm">
            <Icon name={icon} className="mt-0.5 shrink-0 text-text2" />
            {item}
          </li>
        ))}
      </ul>
      {note && (
        <Text variant="cap" secondary>
          {note}
        </Text>
      )}
    </Card>
  );
}
