// Язык интерфейса S43 (DEVELOPMENT_PLAN 4.9; до шага — список на S31): ru / sr-Latn / sr-Cyrl
// сегментами, English — «скоро». Выбор хранится на сервере (ui_locale) — на нём же пишет бот,
// поэтому язык меняет PATCH /me: до ответа отмечен выбранный, интерфейс переключается по ответу,
// без перезагрузки. Если на сервере en (в MVP не выбирается), отмечен текущий язык, и его выбор
// тоже сохраняется.
import type { MeOut } from '@sosed/api-client';
import { getIdentityGetMeQueryKey, useIdentityUpdateMe } from '@sosed/api-client';
import type { Locale } from '@sosed/i18n';
import { LOCALES, LOCALE_LABELS, isLocale, useLocale, useTranslation } from '@sosed/i18n';
import { usePlatform } from '@sosed/platform';
import { Banner, SectionTitle, Segmented, Text } from '@sosed/ui-web';
import { useQueryClient } from '@tanstack/react-query';
import { useEffect, useId } from 'react';

export function Language({ me }: { me: MeOut }) {
  const { t, i18n } = useTranslation('account');
  const { t: common } = useTranslation();
  const locale = useLocale();
  const platform = usePlatform();
  const queryClient = useQueryClient();
  const titleId = useId();
  const saved = isLocale(me.ui_locale) ? me.ui_locale : null;
  // язык сменили в другом месте (бот /language, второе устройство) — интерфейс следует за /me
  useEffect(() => {
    if (saved && saved !== locale) void i18n.changeLanguage(saved);
  }, [i18n, locale, saved]);

  // If-Match не отправляем: mutator отдаёт только тело ответа, ETag из GET /me до экрана не доходит
  const update = useIdentityUpdateMe({
    mutation: {
      // ответ PATCH — тот же MeOut: кладём в кэш раньше смены языка, иначе эффект выше вернёт
      // старый язык из /me
      onSuccess: async (next) => {
        queryClient.setQueryData(getIdentityGetMeQueryKey(), next);
        if (isLocale(next.ui_locale)) await i18n.changeLanguage(next.ui_locale);
      },
      // запрос мог дойти до сервера без ответа — перечитываем /me, но не ждём: иначе мутация
      // остаётся pending до конца перечитывания, без ошибки и с отброшенными нажатиями
      onError: () => {
        void queryClient.invalidateQueries({ queryKey: getIdentityGetMeQueryKey() });
      },
    },
  });
  const pending = update.isPending ? update.variables.data.ui_locale : null;
  const selected = isLocale(pending) ? pending : (saved ?? locale);

  const choose = (next: Locale) => {
    if (update.isPending || next === saved) return;
    platform.haptics.selection();
    update.mutate({ data: { ui_locale: next } });
  };

  return (
    <section aria-labelledby={titleId} className="flex flex-col gap-2">
      <SectionTitle id={titleId}>{t('settings.language')}</SectionTitle>
      <Segmented
        label={t('settings.language')}
        value={selected}
        onChange={choose}
        options={LOCALES.map((option) => ({
          value: option,
          label: <LanguageName locale={option} />,
        }))}
      />
      <Text variant="cap" secondary className="px-4">
        {t('settings.languageSoon')}
      </Text>
      {update.isError && (
        <Banner tone="danger" role="alert">
          {common('profile.languageError')}
        </Banner>
      )}
    </section>
  );
}

/** Самоназвание, как на артборде («Srpski», «Српски»); письмо — для скринридера: на слух
 *  латиница и кириллица звучат одинаково. */
function LanguageName({ locale }: { locale: Locale }) {
  const { name, script } = LOCALE_LABELS[locale];
  return (
    <span lang={locale}>
      {name}
      {/* пробел — снаружи скрытой части: внутри неё его теряет вычисление имени */}
      {script && (
        <>
          {' '}
          <span className="sr-only">({script})</span>
        </>
      )}
    </span>
  );
}
