// S20c «Сколько готовы заплатить?», шаг 3 из 4 (DEVELOPMENT_PLAN 5.2): фикс, диапазон или
// договорная; сумма в RSD; за работу, час или визит. Ориентир цены категории для города
// (`price_hint`, Q22) — справкой; ставка за час ниже минимальной — предупреждение. Язык общения —
// языки, на которых клиент готов говорить. «Только с подтверждённым телефоном» с артборда — v1:
// подтверждение телефона перенесено (решение владельца 2026-10-01).
import type { BudgetType } from '@sosed/api-client';
import { MIN_HOURLY_RSD } from '@sosed/domain';
import type { DraftLanguage, JobDraft } from '@sosed/hooks';
import {
  DRAFT_LANGUAGES,
  DRAFT_UNITS,
  amountOf,
  budgetProblems,
  useCategories,
  useCities,
} from '@sosed/hooks';
import { useFormat, useLocale, useTranslation } from '@sosed/i18n';
import { Banner, Chip, Chips, Field, Heading, Input, Segmented, Text } from '@sosed/ui-web';
import { useState } from 'react';

import { groupDigits } from '../shared/amount.ts';
import { findCategory } from '../shared/categories.ts';
import { useJobDraft } from '../shared/draft.ts';
import { useCreateFlow, useStepButton } from '../shared/flow.ts';
import { WizardHeader } from '../shared/WizardHeader.tsx';

const BUDGET_TYPES: readonly BudgetType[] = ['fixed', 'range', 'negotiable'];

export function BudgetScreen() {
  const { draft, patch } = useJobDraft();
  const flow = useCreateFlow('budget', draft);
  if (!draft) return null;
  return <BudgetForm draft={draft} patch={patch} next={flow.next} />;
}

function BudgetForm({
  draft,
  patch,
  next,
}: {
  draft: JobDraft;
  patch: (patch: Partial<JobDraft>) => void;
  next: () => void;
}) {
  const { t } = useTranslation('jobs');
  const { t: common } = useTranslation();
  const [checked, setChecked] = useState(false);
  const problems = budgetProblems(draft);
  const min = amountOf(draft.budgetMin);
  const lowRate =
    draft.budgetType !== 'negotiable' && draft.budgetUnit === 'hour' && min !== null
      ? min < MIN_HOURLY_RSD
      : false;

  useStepButton({
    text: common('action.next'),
    onClick: () => {
      setChecked(true);
      if (problems.length === 0) next();
    },
  });

  const toggleLanguage = (language: DraftLanguage) => {
    const on = draft.languages.includes(language);
    patch({
      languages: on
        ? draft.languages.filter((item) => item !== language)
        : DRAFT_LANGUAGES.filter((item) => item === language || draft.languages.includes(item)),
    });
  };

  return (
    <section className="flex flex-col gap-4 px-4 pt-3 pb-6">
      <WizardHeader step={3} title={t('create.budget.title')} />
      <Segmented<BudgetType>
        label={t('create.budget.type')}
        value={draft.budgetType}
        onChange={(budgetType) => patch({ budgetType })}
        options={BUDGET_TYPES.map((type) => ({ value: type, label: t(`create.budget.${type}`) }))}
      />
      {draft.budgetType === 'negotiable' ? (
        <Text secondary>{t('create.budget.negotiableHint')}</Text>
      ) : (
        <Amounts draft={draft} patch={patch} problems={checked ? problems : []} />
      )}
      {draft.budgetType !== 'negotiable' && (
        <div className="flex flex-col gap-2">
          <span className="text-sm font-semibold">{t('create.budget.unit')}</span>
          <Chips label={t('create.budget.unit')} wrap>
            {DRAFT_UNITS.map((unit) => (
              <Chip
                key={unit}
                selected={draft.budgetUnit === unit}
                onClick={() => patch({ budgetUnit: unit })}
              >
                {t(`create.budget.units.${unit}`)}
              </Chip>
            ))}
          </Chips>
        </div>
      )}
      {lowRate && (
        <Banner tone="warn" role="status">
          {t('create.budget.lowRate')}
        </Banner>
      )}
      <PriceHint draft={draft} />
      <Heading variant="h3" as="h2">
        {t('create.budget.details')}
      </Heading>
      <div className="flex flex-col gap-2">
        <span className="text-sm font-semibold">{t('create.budget.languages')}</span>
        <Chips label={t('create.budget.languages')} wrap>
          {DRAFT_LANGUAGES.map((language) => {
            const on = draft.languages.includes(language);
            return (
              <Chip
                key={language}
                selected={on}
                icon={on ? 'check' : undefined}
                onClick={() => toggleLanguage(language)}
              >
                {t(`create.budget.langs.${language}`)}
              </Chip>
            );
          })}
        </Chips>
      </div>
    </section>
  );
}

function Amounts({
  draft,
  patch,
  problems,
}: {
  draft: JobDraft;
  patch: (patch: Partial<JobDraft>) => void;
  problems: readonly string[];
}) {
  const { t } = useTranslation('jobs');
  const amount = (
    label: string,
    value: string,
    onChange: (value: string) => void,
    error?: string,
  ) => (
    <Field label={label} error={error}>
      <Input
        inputMode="numeric"
        value={groupDigits(value)}
        suffix={t('create.budget.currency')}
        onChange={(event) => onChange(groupDigits(event.target.value))}
      />
    </Field>
  );
  const missing = problems.includes('amount') ? t('create.budget.missingAmount') : undefined;
  if (draft.budgetType === 'fixed') {
    return amount(
      t('create.budget.amount'),
      draft.budgetMin,
      (budgetMin) => patch({ budgetMin }),
      missing,
    );
  }
  return (
    <div className="grid grid-cols-2 gap-2">
      {amount(
        t('create.budget.from'),
        draft.budgetMin,
        (budgetMin) => patch({ budgetMin }),
        missing,
      )}
      {amount(
        t('create.budget.to'),
        draft.budgetMax,
        (budgetMax) => patch({ budgetMax }),
        problems.includes('range') ? t('create.budget.missingRange') : undefined,
      )}
    </div>
  );
}

/** Ориентир цены категории в городе заявки — справкой, если он есть. */
function PriceHint({ draft }: { draft: JobDraft }) {
  const { t } = useTranslation('jobs');
  const format = useFormat();
  const locale = useLocale();
  const city = useCities(locale).data?.find((item) => item.id === draft.cityId);
  const tree = useCategories(locale, city?.slug).data ?? [];
  const category = draft.categoryId !== null ? findCategory(tree, draft.categoryId) : null;
  const hint = category?.price_hint;
  if (!category || !hint) return null;
  return (
    <Banner tone="info">
      {t('create.budget.hint', {
        category: category.name,
        range: format.moneyRange(hint.min.amount, hint.max.amount),
      })}
    </Banner>
  );
}
