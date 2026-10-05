// S20d «Проверьте заявку», шаг 4 из 4 (DEVELOPMENT_PLAN 5.2): заявка так, как её увидят
// исполнители, и «кто что увидит»: точный адрес — только выбранному, телефон — никому, откликов —
// не больше пяти. «Опубликовать» — POST /jobs с ключом черновика: двойное нажатие и повтор после
// обрыва сети не создают вторую заявку. Потом черновик стирается, а человек — на S21. Правка своей
// заявки (5.6) — «Сохранить изменения»: PATCH с If-Match версии, с которой начали; заявку успели
// изменить в другом месте (412) — «откройте её заново»; сохранили — обратно на S23.
import { ApiError } from '@sosed/api-client';
import { DEFAULT_MAX_RESPONSES, jobWhen, rsdToPara, slotOf } from '@sosed/domain';
import type { JobDraft } from '@sosed/hooks';
import {
  amountOf,
  budgetProblems,
  jobInOf,
  selectableDistricts,
  systemStateOf,
  useCategories,
  useCreateJob,
  useDistricts,
  useUpdateJob,
  whatProblems,
  whenProblems,
} from '@sosed/hooks';
import { useFormat, useLocale, useTranslation } from '@sosed/i18n';
import type { IconName, JobCardBadge } from '@sosed/ui-web';
import { Banner, Card, Heading, Icon, JobCard, LinkButton, Text } from '@sosed/ui-web';
import { useRouter } from '@tanstack/react-router';
import type { ReactNode } from 'react';

import { DirectBanner } from '../shared/DirectBanner.tsx';
import { findCategory } from '../shared/categories.ts';
import type { Editing } from '../shared/draft.ts';
import { useDraftStore, useJobDraft } from '../shared/draft.ts';
import { useCreateFlow, useStepButton } from '../shared/flow.ts';
import { useSlots, useWhenBadge } from '../shared/labels.ts';
import { CREATE_PATHS, managePath } from '../shared/paths.ts';
import { WizardSkeleton } from '../shared/skeletons.tsx';
import { WizardHeader } from '../shared/WizardHeader.tsx';

export function PreviewScreen() {
  const { draft, editing } = useJobDraft();
  const flow = useCreateFlow('preview', draft);
  if (!draft) return <WizardSkeleton step={4} />;
  return <Preview draft={draft} editing={editing} open={flow.open} />;
}

function Preview({
  draft,
  editing,
  open,
}: {
  draft: JobDraft;
  editing: Editing | null;
  open: (step: 'what' | 'when' | 'budget') => void;
}) {
  const { t } = useTranslation('jobs');
  const { t: common } = useTranslation();
  const router = useRouter();
  const clear = useDraftStore((state) => state.clear);
  const patchDraft = useDraftStore((state) => state.patch);
  const endEdit = useDraftStore((state) => state.endEdit);
  const publish = useCreateJob();
  const update = useUpdateJob();
  const mutation = editing ? update : publish;

  useStepButton({
    text: editing ? t('create.preview.save') : common('action.publish'),
    loading: mutation.isPending,
    onClick: () => {
      if (mutation.isPending) return;
      const now = new Date();
      const body = jobInOf(draft, now);
      if (!body) {
        // черновик открыли с середины, а шаг не пройден — вернуться к нему
        if (whatProblems(draft).length > 0) open('what');
        else if (whenProblems(draft, now).length > 0) open('when');
        else if (budgetProblems(draft).length > 0) open('budget');
        return;
      }
      if (editing) {
        update.mutate(
          { jobId: editing.jobId, version: editing.version, body },
          {
            // правку закрываем, когда мастер уже ушёл с экрана: иначе он начал бы её заново
            // с сохранённой заявкой
            onSuccess: (job) =>
              void router.navigate({ to: managePath(job.id), replace: true }).then(endEdit),
          },
        );
        return;
      }
      publish.mutate(
        { body, key: draft.key, directTo: draft.direct?.profileId ?? null },
        {
          // итог S21 — сразу по ответу сервера; черновик стирается, когда мастер уже ушёл с
          // экрана (как у правки): ответа DeviceStorage S20d не ждёт. Повтор с тем же черновиком
          // до стирания — тот же ключ: сервер вернёт ту же заявку
          onSuccess: (job) =>
            void router
              .navigate({ to: CREATE_PATHS.done, search: { job: job.id }, replace: true })
              .then(clear),
        },
      );
    },
  });

  return (
    <section className="flex flex-col gap-4 px-4 pt-3 pb-6">
      <WizardHeader step={4} title={t('create.preview.title')} />
      {draft.direct && !editing && (
        <DirectBanner direct={draft.direct} onAll={() => patchDraft({ direct: null })} />
      )}
      <div className="flex items-center justify-between gap-3">
        <Text variant="cap">{t('create.preview.seenAs')}</Text>
        <LinkButton onClick={() => open('what')} className="-mr-2">
          {t('create.preview.edit')}
        </LinkButton>
      </div>
      <DraftCard draft={draft} />
      <WhoSees draft={draft} />
      <div className="flex items-start gap-2 text-text2">
        <Icon name="shield" size={16} className="mt-0.5 shrink-0" />
        <Text variant="cap">{t('create.preview.moderation')}</Text>
      </div>
      {publish.isError && <PublishError error={publish.error} />}
      {editing && update.isError && (
        <SaveError
          error={update.error}
          onReopen={() =>
            void router.navigate({ to: managePath(editing.jobId), replace: true }).then(endEdit)
          }
        />
      )}
    </section>
  );
}

/** В карточке ленты — до трёх превью (JobCardOut.photos), остальные — на экране заявки S15. */
const FEED_PHOTOS = 3;

/** Заявка карточкой ленты (общий JobCard): так её увидят исполнители сразу после публикации —
 *  «только что», откликов 0 из 5, место — район без расстояния (у каждого исполнителя оно своё). */
function DraftCard({ draft }: { draft: JobDraft }) {
  const { t } = useTranslation('jobs');
  const format = useFormat();
  const locale = useLocale();
  const whenBadge = useWhenBadge();
  const slots = useSlots();
  const tree = useCategories(locale).data ?? [];
  const category = draft.categoryId !== null ? findCategory(tree, draft.categoryId) : null;
  const district = selectableDistricts(useDistricts(draft.cityId, locale).data ?? [], locale).find(
    (item) => item.id === draft.districtId,
  );
  const now = new Date();
  // «когда» — как сервер сохранит его из черновика (jobInOf): тот же бейдж, что в ленте
  const when = draft.when
    ? jobWhen(
        { choice: draft.when, slot: slotOf(draft.slot), day: draft.day, time: draft.time },
        now,
      )
    : null;
  const badges: JobCardBadge[] = when
    ? [
        whenBadge({
          urgency: when.urgency,
          preferred_from: when.preferredFrom?.toISOString() ?? null,
          preferred_to: when.preferredTo?.toISOString() ?? null,
        }),
      ]
    : [];
  const categoryName = category?.name ?? draft.categoryName;
  if (categoryName) badges.push({ label: categoryName, tone: 'mute' });
  const negotiable = draft.budgetType === 'negotiable';
  const min = amountOf(draft.budgetMin);
  const max = draft.budgetType === 'range' ? amountOf(draft.budgetMax) : null;
  return (
    <JobCard
      title={draft.title.trim()}
      budget={
        negotiable
          ? t('card.negotiable')
          : format.price({
              type: draft.budgetType,
              min: min !== null ? rsdToPara(min) : null,
              max: max !== null ? rsdToPara(max) : null,
              unit: draft.budgetUnit,
            })
      }
      negotiable={negotiable}
      badges={badges}
      time={format.relative(now, now)}
      description={draft.description.trim() || null}
      photos={draft.photos.slice(0, FEED_PHOTOS).map((photo) => ({ src: photo.thumb ?? '' }))}
      photoLabel={(number) => t('card.photo', { number })}
      place={district?.name ?? null}
      slots={slots({ max_responses: DEFAULT_MAX_RESPONSES, responses_count: 0 })}
    />
  );
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
/** Правка не сохранилась: заявку уже изменили (412) — открыть её заново; иначе — как публикация. */
function SaveError({ error, onReopen }: { error: unknown; onReopen: () => void }) {
  const { t } = useTranslation('jobs');
  if (!(error instanceof ApiError && error.code === 'stale_version')) {
    return <PublishError error={error} />;
  }
  return (
    <Banner tone="warn" role="alert">
      <span className="flex flex-col items-start gap-2">
        <span>{t('create.preview.stale')}</span>
        <LinkButton onClick={onReopen} className="-ml-2">
          {t('create.preview.reopen')}
        </LinkButton>
      </span>
    </Banner>
  );
}

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
