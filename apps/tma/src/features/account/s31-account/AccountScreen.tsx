// S31 Профиль — заглушка ходячего скелета (DEVELOPMENT_PLAN 0.22): имя и внутренний id из GET /me,
// язык интерфейса пишется через PATCH /me. Экран по макету design/project — в шаге 2.9.
import type { MeOut } from '@sosed/api-client';
import {
  ApiError,
  getIdentityGetMeQueryKey,
  useIdentityGetMe,
  useIdentityUpdateMe,
} from '@sosed/api-client';
import type { Locale } from '@sosed/i18n';
import { LOCALES, LOCALE_NAMES, isLocale, useLocale, useTranslation } from '@sosed/i18n';
import { usePlatform } from '@sosed/platform';
import {
  Avatar,
  Banner,
  Button,
  EmptyState,
  Heading,
  Option,
  SectionTitle,
  Skeleton,
  Text,
} from '@sosed/ui-web';
import { useQueryClient } from '@tanstack/react-query';

export function AccountScreen() {
  const { t } = useTranslation();
  const platform = usePlatform();
  // Без initData (браузер) войти нечем: /me не запрашиваем
  const inTelegram = platform.launch.rawInitData !== null;
  const me = useIdentityGetMe({ query: { enabled: inTelegram } });
  // 401 приходит, когда mutator уже попробовал войти заново по initData и не смог
  const signedOut = !inTelegram || (me.error instanceof ApiError && me.error.status === 401);

  let content;
  if (signedOut) content = <SignedOut />;
  else if (me.data) content = <Account me={me.data} />;
  else if (me.isError) content = <LoadError onRetry={() => void me.refetch()} />;
  else content = <Loading />;

  return (
    <section className="flex flex-col gap-4 px-4 pt-4">
      <Heading variant="h1">{t('nav.profile')}</Heading>
      {content}
    </section>
  );
}

function Account({ me }: { me: MeOut }) {
  const { t, i18n } = useTranslation();
  const locale = useLocale();
  const queryClient = useQueryClient();
  // If-Match не отправляем: mutator отдаёт только тело ответа, ETag из GET /me до экрана не доходит
  const update = useIdentityUpdateMe({
    mutation: {
      onSuccess: async (_, { data }) => {
        if (isLocale(data.ui_locale)) await i18n.changeLanguage(data.ui_locale);
      },
      onSettled: () => queryClient.invalidateQueries({ queryKey: getIdentityGetMeQueryKey() }),
    },
  });
  const selected = update.isPending ? update.variables.data.ui_locale : locale;

  const choose = (next: Locale) => {
    if (update.isPending || next === locale) return;
    update.mutate({ data: { ui_locale: next } });
  };

  return (
    <>
      <div className="flex items-center gap-4">
        {/* имя рядом — аватар для скринридера лишний */}
        <span aria-hidden="true">
          <Avatar name={me.display_name} size="lg" />
        </span>
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <Heading variant="h2" as="h2">
            {me.display_name}
          </Heading>
          <Text variant="cap" className="break-all">
            {t('profile.id', { id: me.id })}
          </Text>
        </div>
      </div>
      <div className="flex flex-col gap-2">
        <SectionTitle>{t('profile.language')}</SectionTitle>
        <div role="radiogroup" aria-label={t('profile.language')} className="flex flex-col gap-2">
          {LOCALES.map((option) => (
            <Option
              key={option}
              title={<span lang={option}>{LOCALE_NAMES[option]}</span>}
              checked={option === selected}
              onChange={() => choose(option)}
            />
          ))}
        </div>
        {update.isError && (
          <Banner tone="danger" role="alert">
            {t('profile.languageError')}
          </Banner>
        )}
      </div>
    </>
  );
}

function Loading() {
  const { t } = useTranslation();
  return (
    <div role="status" aria-label={t('profile.loading')} className="flex items-center gap-4">
      <Skeleton round className="size-22" />
      <div className="flex flex-1 flex-col gap-2">
        <Skeleton className="h-6 w-2/3" />
        <Skeleton className="h-4 w-1/2" />
      </div>
    </div>
  );
}

function LoadError({ onRetry }: { onRetry: () => void }) {
  const { t } = useTranslation();
  return (
    <EmptyState
      as="h2"
      icon="alert"
      title={t('error.title')}
      action={
        <Button variant="secondary" onClick={onRetry}>
          {t('action.retry')}
        </Button>
      }
    >
      {t('error.text')}
    </EmptyState>
  );
}

function SignedOut() {
  const { t } = useTranslation();
  return (
    <EmptyState as="h2" icon="send" title={t('profile.signedOutTitle')}>
      {t('profile.signedOutText')}
    </EmptyState>
  );
}
