// S32b «Чем вы занимаетесь?», шаг 2 из 3 (DEVELOPMENT_PLAN 2.9): категории (PUT
// /me/profile/categories), «коротко о себе», «о себе» и языки (PATCH /me/profile). На сервер уходит
// только изменённое; несохранённый ввод живёт в черновике мастера, пока человек ходит по шагам.
// Категории — листья каталога: специалист выбирает услуги, а не разделы; первая — основная.
import type { CategoryOut, Language, ProfileOut, ProfileUpdateIn } from '@sosed/api-client';
import { specialistsSetMyCategories, specialistsUpdateMyProfile } from '@sosed/api-client';
import { leafCategories, useCategories } from '@sosed/hooks';
import type { Locale } from '@sosed/i18n';
import { useLocale, useTranslation } from '@sosed/i18n';
import { useBackButton, usePlatform } from '@sosed/platform';
import { Chip, Chips, Field, Input, Textarea } from '@sosed/ui-web';
import { useMutation } from '@tanstack/react-query';
import { useId, useState } from 'react';

import { LoadState } from '../shared/LoadState.tsx';
import { SaveError } from '../shared/SaveError.tsx';
import { WizardHeader } from '../shared/WizardHeader.tsx';
import { useChipList } from '../shared/chips.ts';
import { useBecomeFlow, useDraftProfile, useStepButton } from '../shared/flow.ts';
import { sameList } from '../shared/same.ts';
import { useBecomeStore } from '../shared/store.ts';

/** Как на артборде: четыре категории и «Другие категории». */
const VISIBLE_CATEGORIES = 4;
/** MAX_CATEGORIES, MAX_HEADLINE, MAX_ABOUT профиля (backend specialists/domain/profile.py). */
const MAX_CATEGORIES = 5;
const MAX_HEADLINE = 80;
const MAX_ABOUT = 4000;
const LANGUAGES: readonly Language[] = ['ru', 'sr', 'en', 'uk'];

/** Язык, отмеченный по умолчанию: язык интерфейса. */
function spokenLanguage(locale: Locale): Language {
  return locale === 'ru' ? 'ru' : 'sr';
}

export function AboutScreen() {
  const { t } = useTranslation('specialist');
  const flow = useBecomeFlow();
  const { query, draft } = useDraftProfile();
  const categories = useCategories(useLocale());
  useBackButton(() => flow.back('type'));

  if (draft && categories.data) return <AboutForm profile={draft} tree={categories.data} />;
  const failed = query.isError || categories.isError;
  return (
    <section className="flex flex-col gap-3.5 px-4 pt-3 pb-6">
      <WizardHeader step={2} title={t('become.about.title')} />
      <LoadState
        error={failed ? (query.error ?? categories.error) : null}
        onRetry={() => {
          if (query.isError) void query.refetch();
          if (categories.isError) void categories.refetch();
        }}
        retrying={query.isFetching || categories.isFetching}
      />
    </section>
  );
}

function AboutForm({ profile, tree }: { profile: ProfileOut; tree: CategoryOut[] }) {
  const { t } = useTranslation('specialist');
  const { t: common } = useTranslation();
  const locale = useLocale();
  const platform = usePlatform();
  const flow = useBecomeFlow();
  const input = useBecomeStore();
  const categoriesId = useId();
  const languagesId = useId();
  const [limited, setLimited] = useState(false);
  // незаполненное подсвечиваем после первого нажатия «Далее»
  const [checked, setChecked] = useState(false);

  const categoryIds = input.categoryIds ?? profile.category_ids;
  const headline = input.headline ?? profile.headline ?? '';
  const about = input.about ?? profile.about ?? '';
  const languages =
    input.languages ??
    (profile.languages.length > 0 ? profile.languages : [spokenLanguage(locale)]);
  const leaves = leafCategories(tree);
  const chips = useChipList(leaves, categoryIds, VISIBLE_CATEGORIES);
  const missing = {
    categories: categoryIds.length === 0,
    headline: headline.trim() === '',
  };

  const save = useMutation({
    mutationFn: async () => {
      let saved = profile;
      if (!sameList(categoryIds, profile.category_ids)) {
        saved = await specialistsSetMyCategories({ category_ids: categoryIds });
        flow.saved(saved);
      }
      const patch: ProfileUpdateIn = {};
      if (headline.trim() !== (profile.headline ?? '')) patch.headline = headline.trim();
      if (about.trim() !== (profile.about ?? '')) patch.about = about.trim();
      if (!sameList(languages, profile.languages)) patch.languages = languages;
      if (Object.keys(patch).length > 0) saved = await specialistsUpdateMyProfile(patch);
      return saved;
    },
    onSuccess: (saved) => {
      flow.saved(saved);
      input.set({ categoryIds: null, headline: null, about: null, languages: null });
      flow.open('area');
    },
  });

  const submit = () => {
    if (save.isPending) return;
    if (missing.categories || missing.headline) {
      setChecked(true);
      platform.haptics.notification('error');
      return;
    }
    save.mutate();
  };
  useStepButton({ text: common('action.next'), onClick: submit, loading: save.isPending });

  const toggleCategory = (id: number) => {
    if (categoryIds.includes(id)) {
      input.set({ categoryIds: categoryIds.filter((other) => other !== id) });
      setLimited(false);
    } else if (categoryIds.length >= MAX_CATEGORIES) {
      setLimited(true);
      platform.haptics.notification('warning');
      return;
    } else {
      input.set({ categoryIds: [...categoryIds, id] });
    }
    platform.haptics.selection();
  };
  const toggleLanguage = (language: Language) => {
    platform.haptics.selection();
    const next = languages.includes(language)
      ? languages.filter((other) => other !== language)
      : [...languages, language];
    input.set({ languages: LANGUAGES.filter((known) => next.includes(known)) });
  };

  return (
    <section className="flex flex-col gap-3.5 px-4 pt-3 pb-6">
      <WizardHeader step={2} title={t('become.about.title')} />
      <section aria-labelledby={categoriesId} className="flex flex-col gap-2">
        <h2 id={categoriesId} className="m-0 text-sm font-semibold">
          {t('become.about.categories')}
        </h2>
        <Chips wrap>
          {chips.visible.map((category) => {
            const on = categoryIds.includes(category.id);
            return (
              <Chip
                key={category.id}
                selected={on}
                icon={on ? 'check' : undefined}
                onClick={() => toggleCategory(category.id)}
              >
                {category.name}
              </Chip>
            );
          })}
          {chips.hidden > 0 && (
            <Chip expanded={chips.expanded} onClick={chips.toggle}>
              {t(chips.expanded ? 'become.about.lessCategories' : 'become.about.moreCategories')}
            </Chip>
          )}
        </Chips>
        <p role="status" className="m-0 text-cap empty:hidden">
          {limited && t('become.about.categoriesLimit', { count: MAX_CATEGORIES })}
        </p>
        {checked && missing.categories && (
          <p role="alert" className="m-0 text-cap text-danger">
            {t('become.missing.category_ids')}
          </p>
        )}
      </section>
      <Field
        label={t('become.about.headline')}
        hint={t('become.about.headlineHint', { count: headline.length, max: MAX_HEADLINE })}
        error={checked && missing.headline ? t('become.missing.headline') : undefined}
      >
        <Input
          value={headline}
          maxLength={MAX_HEADLINE}
          placeholder={t('become.about.headlinePlaceholder')}
          onChange={(event) => input.set({ headline: event.target.value })}
        />
      </Field>
      <Field label={t('become.about.about')} hint={t('become.about.aboutHint')}>
        <Textarea
          rows={3}
          value={about}
          maxLength={MAX_ABOUT}
          placeholder={t('become.about.aboutPlaceholder')}
          onChange={(event) => input.set({ about: event.target.value })}
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
      {save.isError && <SaveError error={save.error} />}
    </section>
  );
}
