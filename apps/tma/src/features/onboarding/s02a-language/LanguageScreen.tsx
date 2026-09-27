// S02a «Язык и город», шаг 1 из 3 (DEVELOPMENT_PLAN 1.5b). Язык — сразу во всём интерфейсе, без
// перезагрузки: по нему же перечитываются названия городов. На сервер выбор уходит по MainButton
// «Далее» одним PATCH /me {ui_locale, home_city_id}. English и города «скоро» видны, но не
// выбираются. Первый шаг: «Назад» нет, в шапке Telegram — «Закрыть».
import type { CityOut } from '@sosed/api-client';
import { useIdentityGetMe, useIdentityUpdateMe } from '@sosed/api-client';
import { defaultCity, isSelectableCity, useCities } from '@sosed/hooks';
import type { Locale } from '@sosed/i18n';
import { LOCALES, LOCALE_LABELS, UPCOMING_LOCALES, useLocale, useTranslation } from '@sosed/i18n';
import { usePlatform } from '@sosed/platform';
import { Badge, Button, Option, RadioGroup, SectionTitle, Skeleton } from '@sosed/ui-web';
import { useId } from 'react';

import { SaveError } from '../shared/SaveError.tsx';
import { StepHeader } from '../shared/StepHeader.tsx';
import { useOnboardingFlow, useStepButton } from '../shared/flow.ts';
import { useOnboardingStore } from '../shared/store.ts';

export function LanguageScreen() {
  const { t, i18n } = useTranslation('onboarding');
  const { t: common } = useTranslation();
  const locale = useLocale();
  const platform = usePlatform();
  const flow = useOnboardingFlow();
  const me = useIdentityGetMe();
  const cities = useCities(locale);
  const draftCity = useOnboardingStore((state) => state.cityId);
  const setDraft = useOnboardingStore((state) => state.set);
  const cityId =
    draftCity ?? (cities.data ? defaultCity(cities.data, me.data?.home_city_id ?? null) : null);

  const update = useIdentityUpdateMe({
    mutation: { onSuccess: (next) => flow.saved('language', next) },
  });
  const submit = () => {
    if (update.isPending || cityId === null) return;
    update.mutate({ data: { ui_locale: locale, home_city_id: cityId } });
  };
  useStepButton({ text: common('action.next'), onClick: submit, loading: update.isPending });

  const chooseLanguage = (next: Locale) => {
    if (next === locale) return;
    platform.haptics.selection();
    void i18n.changeLanguage(next);
  };
  const chooseCity = (id: number) => {
    platform.haptics.selection();
    setDraft({ cityId: id });
  };

  const languageTitle = useId();
  const cityTitle = useId();
  return (
    <section className="flex flex-col gap-5 px-4 pt-4 pb-6">
      <StepHeader step={1} title={t('language.title')} intro={t('language.intro')} />

      <div className="flex flex-col gap-2">
        <SectionTitle>
          <span id={languageTitle}>{t('language.section')}</span>
        </SectionTitle>
        <RadioGroup labelledBy={languageTitle} className="flex flex-col gap-2">
          {LOCALES.map((option) => (
            <Option
              key={option}
              control="start"
              title={<LanguageName locale={option} />}
              checked={option === locale}
              onChange={() => chooseLanguage(option)}
            />
          ))}
          {UPCOMING_LOCALES.map((upcoming) => (
            <Option
              key={upcoming.code}
              control="start"
              disabled
              title={
                <span lang={upcoming.code} className="font-semibold">
                  {upcoming.name}
                </span>
              }
              trailing={<Badge>{t('language.soon')}</Badge>}
              checked={false}
              onChange={() => undefined}
            />
          ))}
        </RadioGroup>
      </div>

      <div className="flex flex-col gap-2">
        <SectionTitle>
          <span id={cityTitle}>{t('city.section')}</span>
        </SectionTitle>
        {cities.data ? (
          <RadioGroup labelledBy={cityTitle} className="flex flex-col gap-2">
            {cities.data.map((city) => (
              <CityOption
                key={city.id}
                city={city}
                checked={city.id === cityId}
                onChoose={() => chooseCity(city.id)}
              />
            ))}
          </RadioGroup>
        ) : cities.isError ? (
          <div className="flex flex-col items-start gap-3">
            <SaveError error={cities.error} message={t('city.loadError')} />
            <Button
              variant="secondary"
              icon="refresh"
              onClick={() => void cities.refetch()}
              disabled={cities.isFetching}
              aria-busy={cities.isFetching}
            >
              {common('action.retry')}
            </Button>
          </div>
        ) : (
          <div role="status" className="flex flex-col gap-2">
            <span className="sr-only">{t('city.loading')}</span>
            <Skeleton radius="panel" className="h-16" />
            <Skeleton radius="panel" className="h-14" />
          </div>
        )}
      </div>

      {update.isError && <SaveError error={update.error} />}
    </section>
  );
}

/** «Srpski · latinica»: самоназвание полужирным, письмо — подписью, язык разметки — свой. */
function LanguageName({ locale }: { locale: Locale }) {
  const { name, script } = LOCALE_LABELS[locale];
  return (
    <span lang={locale}>
      <span className="font-semibold">{name}</span>
      {script && (
        <>
          {' '}
          <span className="text-cap text-text2">· {script}</span>
        </>
      )}
    </span>
  );
}

function CityOption({
  city,
  checked,
  onChoose,
}: {
  city: CityOut;
  checked: boolean;
  onChoose: () => void;
}) {
  const { t } = useTranslation('onboarding');
  const selectable = isSelectableCity(city);
  return (
    <Option
      control="start"
      disabled={!selectable}
      title={<span className="font-semibold">{city.name}</span>}
      description={selectable ? t('city.pilot') : undefined}
      trailing={selectable ? undefined : <Badge>{t('city.soon')}</Badge>}
      checked={checked}
      onChange={onChoose}
    />
  );
}
