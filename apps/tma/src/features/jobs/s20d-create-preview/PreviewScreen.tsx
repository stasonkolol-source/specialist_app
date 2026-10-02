// S20d «Проверьте заявку», шаг 4 из 4 (DEVELOPMENT_PLAN 5.2): заявка так, как её увидят
// исполнители, и «кто что увидит»: точный адрес — только выбранному, телефон — никому, откликов —
// не больше пяти. «Опубликовать» — POST /jobs с ключом черновика: двойное нажатие и повтор после
// обрыва сети не создают вторую заявку. Потом черновик стирается, а человек — на S21.
import { ApiError } from '@sosed/api-client';
import { DEFAULT_MAX_RESPONSES, rsdToPara } from '@sosed/domain';
import type { JobDraft } from '@sosed/hooks';
import {
  amountOf,
  budgetProblems,
  draftSlot,
  jobInOf,
  selectableDistricts,
  systemStateOf,
  useCategories,
  useCities,
  useCreateJob,
  useDistricts,
  whatProblems,
  whenProblems,
} from '@sosed/hooks';
import { useFormat, useLocale, useTranslation } from '@sosed/i18n';
import type { IconName } from '@sosed/ui-web';
import { Badge, Banner, Card, Heading, Icon, LinkButton, Photo, Text } from '@sosed/ui-web';
import { useRouter } from '@tanstack/react-router';
import type { ReactNode } from 'react';

import { findCategory } from '../shared/categories.ts';
import { useDraftStore, useJobDraft } from '../shared/draft.ts';
import { useCreateFlow, useStepButton } from '../shared/flow.ts';
import { CREATE_PATHS } from '../shared/paths.ts';
import { WizardHeader } from '../shared/WizardHeader.tsx';

export function PreviewScreen() {
  const { draft } = useJobDraft();
  const flow = useCreateFlow('preview', draft);
  if (!draft) return null;
  return <Preview draft={draft} open={flow.open} />;
}

function Preview({
  draft,
  open,
}: {
  draft: JobDraft;
  open: (step: 'what' | 'when' | 'budget') => void;
}) {
  const { t } = useTranslation('jobs');
  const { t: common } = useTranslation();
  const router = useRouter();
  const clear = useDraftStore((state) => state.clear);
  const publish = useCreateJob();

  useStepButton({
    text: common('action.publish'),
    loading: publish.isPending,
    onClick: () => {
      if (publish.isPending) return;
      const now = new Date();
      const body = jobInOf(draft, now);
      if (!body) {
        // черновик открыли с середины, а шаг не пройден — вернуться к нему
        if (whatProblems(draft).length > 0) open('what');
        else if (whenProblems(draft, now).length > 0) open('when');
        else if (budgetProblems(draft).length > 0) open('budget');
        return;
      }
      publish.mutate(
        { body, key: draft.key },
        {
          onSuccess: async (job) => {
            await clear();
            void router.navigate({
              to: CREATE_PATHS.done,
              search: { job: job.id },
              replace: true,
            });
          },
        },
      );
    },
  });

  return (
    <section className="flex flex-col gap-4 px-4 pt-3 pb-6">
      <WizardHeader step={4} title={t('create.preview.title')} />
      <div className="flex items-center justify-between gap-3">
        <Text variant="cap">{t('create.preview.seenAs')}</Text>
        <LinkButton onClick={() => open('what')} className="-mr-2">
          {t('create.preview.edit')}
        </LinkButton>
      </div>
      <JobCard draft={draft} />
      <WhoSees draft={draft} />
      <div className="flex items-start gap-2 text-text2">
        <Icon name="shield" size={16} className="mt-0.5 shrink-0" />
        <Text variant="cap">{t('create.preview.moderation')}</Text>
      </div>
      {publish.isError && <PublishError error={publish.error} />}
    </section>
  );
}

/** Карточка заявки, как в ленте исполнителя: заголовок и бюджет, когда, категория, место. */
function JobCard({ draft }: { draft: JobDraft }) {
  const { t } = useTranslation('jobs');
  const { t: common } = useTranslation();
  const format = useFormat();
  const locale = useLocale();
  const tree = useCategories(locale).data ?? [];
  const category = draft.categoryId !== null ? findCategory(tree, draft.categoryId) : null;
  const when = useWhenLabel(draft);
  const city = useCities(locale).data?.find((item) => item.id === draft.cityId) ?? null;
  const district = selectableDistricts(
    useDistricts(draft.cityId, locale).data ?? [],
    locale,
  ).find((item) => item.id === draft.districtId);
  const min = amountOf(draft.budgetMin);
  const max = amountOf(draft.budgetMax);
  const budget = format.price({
    type: draft.budgetType,
    min: min !== null ? rsdToPara(min) : null,
    max: max !== null ? rsdToPara(max) : null,
    unit: draft.budgetUnit,
  });
  return (
    <Card className="flex flex-col gap-3">
      <div className="flex items-start justify-between gap-3">
        <Heading variant="h3" as="h2">
          {draft.title.trim()}
        </Heading>
        <span className="shrink-0 text-h3">{budget}</span>
      </div>
      <div className="flex flex-wrap gap-1.5">
        <Badge tone="info" icon="clock">
          {when}
        </Badge>
        {(category?.name ?? draft.categoryName) && (
          <Badge>{category?.name ?? draft.categoryName}</Badge>
        )}
      </div>
      {draft.description.trim() && <Text>{draft.description.trim()}</Text>}
      {draft.photos.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {draft.photos.map((photo, index) => (
            <Photo
              key={photo.id}
              src={photo.thumb ?? undefined}
              alt={t('create.what.photo', { number: index + 1 })}
              className="size-14"
            />
          ))}
        </div>
      )}
      <div className="flex items-center justify-between gap-3 text-text2">
        <span className="flex min-w-0 items-center gap-1.5">
          <Icon name="pin" size={16} className="shrink-0" />
          <Text as="span" variant="cap">
            {[district?.name, city?.name].filter(Boolean).join(', ')}
          </Text>
        </span>
        <span className="flex shrink-0 items-center gap-2">
          <span aria-hidden="true" className="flex gap-1">
            {Array.from({ length: DEFAULT_MAX_RESPONSES }, (_, index) => (
              <i key={index} className="h-1 w-3 rounded-full bg-line" />
            ))}
          </span>
          <Text as="span" variant="cap">
            {common('count.responsesOf', { count: 0, total: DEFAULT_MAX_RESPONSES })}
          </Text>
        </span>
      </div>
    </Card>
  );
}

/** «Сегодня 18–21», «Срочно», «На неделе», «завтра в 10:00». */
function useWhenLabel(draft: JobDraft): string {
  const { t } = useTranslation('jobs');
  const { t: common } = useTranslation();
  const format = useFormat();
  const slot = draftSlot(draft);
  if (slot) return t('create.preview.todaySlot', { from: slot[0], to: slot[1] });
  const body = jobInOf(draft, new Date());
  if (draft.when === 'date' && body?.preferred_from) {
    return format.calendar(new Date(body.preferred_from));
  }
  if (draft.when === 'week') return common('urgency.this_week');
  return common(`urgency.${draft.when === 'asap' ? 'asap' : 'today'}`);
}

function WhoSees({ draft }: { draft: JobDraft }) {
  const { t } = useTranslation('jobs');
  const address = draft.address.trim();
  return (
    <Card className="flex flex-col gap-3">
      <Heading variant="h3" as="h2">
        {t('create.preview.whoSees')}
      </Heading>
      <Who icon="eye" who={t('create.preview.everyone')}>
        {t('create.preview.everyoneText')}
      </Who>
      <Who icon="lock" who={t('create.preview.chosen')}>
        {address
          ? t('create.preview.chosenText', { address })
          : t('create.preview.chosenNoAddress')}
      </Who>
      <Who icon="phone" who={t('create.preview.nobody')}>
        {t('create.preview.nobodyText')}
      </Who>
      <Who icon="users" who={t('create.preview.limit', { count: DEFAULT_MAX_RESPONSES })}>
        {t('create.preview.limitText')}
      </Who>
    </Card>
  );
}

function Who({ icon, who, children }: { icon: IconName; who: string; children: ReactNode }) {
  return (
    <div className="flex items-start gap-2.5">
      <Icon name={icon} className="mt-0.5 shrink-0 text-accent" />
      <Text>
        <b>{who}</b> {children}
      </Text>
    </div>
  );
}

/** Нет сети, лимит новичка (429 — текст сервера), прочий отказ — с текстом сервера или общим. */
function PublishError({ error }: { error: unknown }) {
  const { t } = useTranslation('jobs');
  const { t: common } = useTranslation();
  const offline = systemStateOf(error).kind === 'offline';
  const detail = error instanceof ApiError && error.status < 500 ? error.problem.detail : null;
  return (
    <Banner tone="danger" role="alert" icon={offline ? 'wifi-off' : 'alert'}>
      {offline ? common('offline.textEmpty') : (detail ?? t('create.preview.publishError'))}
    </Banner>
  );
}
