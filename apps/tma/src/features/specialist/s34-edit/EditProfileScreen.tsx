// S34 Редактирование профиля (DEVELOPMENT_PLAN 2.10–2.11): фото профиля (AvatarField — меняется
// сразу), имя, «коротко о себе», «о себе», языки и районы выезда → PATCH /me/profile и
// PUT /me/profile/areas, только изменённое. Правки опубликованного профиля видны сразу, текст
// уходит на автопроверку.
import type { DistrictOut, Language, ProfileOut, ProfileUpdateIn } from '@sosed/api-client';
import { specialistsSetMyAreas, specialistsUpdateMyProfile } from '@sosed/api-client';
import { selectableDistricts, useDistricts, useMyProfile } from '@sosed/hooks';
import { useLocale, useTranslation } from '@sosed/i18n';
import { useBackButton, usePlatform } from '@sosed/platform';
import { Chip, Chips, Field, Heading, Icon, Input, Text, Textarea, cx } from '@sosed/ui-web';
import { useMutation } from '@tanstack/react-query';
import { useRouter } from '@tanstack/react-router';
import { useEffect, useId, useState } from 'react';

import { LoadState } from '../shared/LoadState.tsx';
import { SaveError } from '../shared/SaveError.tsx';
import { useChipList } from '../shared/chips.ts';
import { useBecomeFlow, useStepButton } from '../shared/flow.ts';
import { ACCOUNT_PATH, CABINET_PATHS } from '../shared/paths.ts';
import { sameList } from '../shared/same.ts';
import { AvatarField } from './AvatarField.tsx';

/** MAX_NAME, MAX_HEADLINE, MAX_ABOUT, MAX_AREAS профиля (backend specialists/domain/profile.py). */
const MAX_NAME = 64;
const MAX_HEADLINE = 80;
const MAX_ABOUT = 4000;
const MAX_AREAS = 30;
const LANGUAGES: readonly Language[] = ['ru', 'sr', 'en', 'uk'];
/** Районов в свёрнутом поле: «Лиман, Грбавица, Центр и ещё 1». */
const NAMED_AREAS = 3;

export function EditProfileScreen() {
  const { t } = useTranslation('specialist');
  const router = useRouter();
  const locale = useLocale();
  const profile = useMyProfile();
  const districts = useDistricts(profile.data?.city_id ?? null, locale);
  const back = () => {
    if (router.history.canGoBack()) router.history.back();
    else void router.navigate({ to: CABINET_PATHS.home, replace: true });
  };
  useBackButton(back);
  useEffect(() => {
    if (profile.data === null) void router.navigate({ to: ACCOUNT_PATH, replace: true });
  }, [profile.data, router]);

  if (profile.data && districts.data) {
    return (
      <EditForm
        profile={profile.data}
        districts={selectableDistricts(districts.data, locale)}
        onSaved={back}
      />
    );
  }
  const failed = [profile, districts].find((load) => load.isError);
  return (
    <section className="flex flex-col gap-3.5 px-4 pt-3 pb-6">
      <Heading variant="h2" as="h1">
        {t('cabinet.edit.title')}
      </Heading>
      <LoadState
        error={failed ? failed.error : null}
        onRetry={() => {
          if (profile.isError) void profile.refetch();
          if (districts.isError) void districts.refetch();
        }}
        retrying={profile.isFetching || districts.isFetching}
      />
    </section>
  );
}

function EditForm({
  profile,
  districts,
  onSaved,
}: {
  profile: ProfileOut;
  districts: DistrictOut[];
  onSaved: () => void;
}) {
  const { t } = useTranslation('specialist');
  const platform = usePlatform();
  const flow = useBecomeFlow();
  const languagesId = useId();
  const areasId = useId();
  const [name, setName] = useState(profile.display_name);
  const [headline, setHeadline] = useState(profile.headline ?? '');
  const [about, setAbout] = useState(profile.about ?? '');
  const [languages, setLanguages] = useState<Language[]>(profile.languages);
  const [districtIds, setDistrictIds] = useState<number[]>(profile.district_ids);
  const [areasOpen, setAreasOpen] = useState(false);
  // незаполненное подсвечиваем после первого нажатия «Сохранить»
  const [checked, setChecked] = useState(false);
  const chips = useChipList(districts, districtIds, districts.length);
  const travels = profile.work_modes.includes('at_client');
  const missing = {
    name: name.trim() === '',
    headline: headline.trim() === '',
    areas: travels && districtIds.length === 0,
  };

  const save = useMutation({
    mutationFn: async () => {
      let saved = profile;
      const patch: ProfileUpdateIn = {};
      if (name.trim() !== profile.display_name) patch.display_name = name.trim();
      if (headline.trim() !== (profile.headline ?? '')) patch.headline = headline.trim();
      if (about.trim() !== (profile.about ?? '')) patch.about = about.trim();
      if (!sameList(languages, profile.languages)) patch.languages = languages;
      if (Object.keys(patch).length > 0) {
        saved = await specialistsUpdateMyProfile(patch);
        flow.saved(saved);
      }
      if (!sameList(districtIds, profile.district_ids)) {
        saved = await specialistsSetMyAreas({ district_ids: districtIds });
      }
      return saved;
    },
    onSuccess: (saved) => {
      flow.saved(saved);
      platform.haptics.notification('success');
      onSaved();
    },
  });

  const submit = () => {
    if (save.isPending) return;
    if (missing.name || missing.headline || missing.areas) {
      setChecked(true);
      platform.haptics.notification('error');
      return;
    }
    save.mutate();
  };
  useStepButton({ text: t('cabinet.edit.save'), onClick: submit, loading: save.isPending });

  const toggleLanguage = (language: Language) => {
    platform.haptics.selection();
    const next = languages.includes(language)
      ? languages.filter((other) => other !== language)
      : [...languages, language];
    setLanguages(LANGUAGES.filter((known) => next.includes(known)));
  };
  const toggleDistrict = (id: number) => {
    if (districtIds.includes(id)) setDistrictIds(districtIds.filter((other) => other !== id));
    else if (districtIds.length < MAX_AREAS) setDistrictIds([...districtIds, id]);
    else {
      platform.haptics.notification('warning');
      return;
    }
    platform.haptics.selection();
  };

  const names = districtIds
    .map((id) => districts.find((district) => district.id === id)?.name)
    .filter((value): value is string => Boolean(value));
  const summary =
    names.length === 0
      ? t('cabinet.edit.areasNone')
      : names.length <= NAMED_AREAS
        ? names.join(', ')
        : t('cabinet.edit.areasSummary', {
            names: names.slice(0, NAMED_AREAS).join(', '),
            count: names.length - NAMED_AREAS,
          });
  const published = profile.status === 'published' || profile.status === 'hidden';

  return (
    <section className="flex flex-col gap-3.5 px-4 pt-3 pb-6">
      <Heading variant="h2" as="h1">
        {t('cabinet.edit.title')}
      </Heading>
      <AvatarField profile={profile} />
      <Field
        label={t('cabinet.edit.name')}
        error={checked && missing.name ? t('cabinet.edit.nameMissing') : undefined}
      >
        <Input
          value={name}
          maxLength={MAX_NAME}
          autoComplete="name"
          onChange={(event) => setName(event.target.value)}
        />
      </Field>
      <Field
        label={t('become.about.headline')}
        hint={t('become.about.headlineHint', { count: headline.length, max: MAX_HEADLINE })}
        error={checked && missing.headline ? t('become.missing.headline') : undefined}
      >
        <Input
          value={headline}
          maxLength={MAX_HEADLINE}
          placeholder={t('become.about.headlinePlaceholder')}
          onChange={(event) => setHeadline(event.target.value)}
        />
      </Field>
      <Field
        label={t('become.about.about')}
        hint={t('cabinet.edit.aboutHint', { count: about.length, max: MAX_ABOUT })}
      >
        <Textarea
          rows={3}
          value={about}
          maxLength={MAX_ABOUT}
          placeholder={t('become.about.aboutPlaceholder')}
          onChange={(event) => setAbout(event.target.value)}
        />
      </Field>
      <section aria-labelledby={languagesId} className="flex flex-col gap-2">
        <h2 id={languagesId} className="m-0 text-sm font-semibold">
          {t('become.about.languages')}
        </h2>
        <Chips wrap>
          {LANGUAGES.map((language) => {
            const on = languages.includes(language);
            return (
              <Chip
                key={language}
                selected={on}
                icon={on ? 'check' : undefined}
                onClick={() => toggleLanguage(language)}
              >
                {t(`become.about.language.${language}`)}
              </Chip>
            );
          })}
        </Chips>
      </section>
      <section aria-labelledby={areasId} className="flex flex-col gap-1.5">
        <h2 id={areasId} className="m-0 text-sm font-semibold">
          {t('cabinet.edit.areas')}
        </h2>
        <button
          type="button"
          aria-expanded={areasOpen}
          aria-describedby={areasId}
          onClick={() => setAreasOpen(!areasOpen)}
          className={cx(
            'flex h-12 w-full items-center gap-2 rounded-field border bg-surface px-3.5 text-left text-input text-text',
            checked && missing.areas ? 'border-danger' : 'border-field',
            'outline-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent',
          )}
        >
          <span className="min-w-0 flex-1 truncate">{summary}</span>
          <Icon name="chev-down" className={cx('text-text2', areasOpen && 'rotate-180')} />
        </button>
        {areasOpen && (
          <Chips wrap>
            {chips.visible.map((district) => {
              const on = districtIds.includes(district.id);
              return (
                <Chip
                  key={district.id}
                  selected={on}
                  icon={on ? 'check' : undefined}
                  onClick={() => toggleDistrict(district.id)}
                >
                  {district.name}
                </Chip>
              );
            })}
          </Chips>
        )}
        {checked && missing.areas && (
          <p role="alert" className="m-0 text-cap text-danger">
            {t('become.missing.area_ids')}
          </p>
        )}
      </section>
      {published && <Text variant="cap">{t('cabinet.edit.postModeration')}</Text>}
      {save.isError && <SaveError error={save.error} />}
    </section>
  );
}
