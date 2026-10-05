// S20d «Проверьте заявку», шаг 4 из 4 (DEVELOPMENT_PLAN 5.2): заявка так, как её увидят
// исполнители, и одной строкой «Адрес и контакты увидит только выбранный исполнитель»; под
// «Подробнее» — кто что увидит: точный адрес — только выбранному, Telegram — ему же после
// договорённости (если не скрыт в настройках), телефон — никому, откликов — не больше пяти; прямой
// запрос увидит только этот специалист (UX_GUIDANCE §5: подробности — по запросу). «Опубликовать» — POST /jobs с ключом черновика: двойное
// нажатие и повтор после обрыва сети не создают вторую заявку, второе нажатие до ответа на первое
// не уходит вовсе. Потом черновик стирается, а человек — на S21. Правка своей заявки (5.6) —
// «Сохранить изменения»: PATCH с If-Match версии, с которой начали (ложный 412 от автопроверки хук
// повторяет сам); заявку правда изменили в другом месте — мастер показывает её текущую версию,
// правку вносят заново; сохранили — обратно на S23.
import {
  ApiError,
  useIdentityGetMe,
  useNotificationsGetNotificationSettings,
} from '@sosed/api-client';
import { DEFAULT_MAX_RESPONSES, jobWhen, rsdToPara, slotOf } from '@sosed/domain';
import type { JobDraft } from '@sosed/hooks';
import {
  StaleJobError,
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
import { Banner, Card, Icon, JobCard, LinkButton, Text } from '@sosed/ui-web';
import { useRouter } from '@tanstack/react-router';
import type { ReactNode } from 'react';
import { useId, useRef, useState } from 'react';

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
  // может ли бот писать — S21 решает, обещать ли «бот напишет»: спрашиваем заранее, чтобы его
  // строка не менялась на глазах
  useNotificationsGetNotificationSettings();
  const mutation = editing ? update : publish;
  // два нажатия до перерисовки (двойной тап) видят isPending ещё ложным: отправка — одна
  const sending = useRef(false);
  const settled = () => {
    sending.current = false;
  };

  useStepButton({
    text: editing ? t('create.preview.save') : common('action.publish'),
    loading: mutation.isPending,
    onClick: () => {
      if (sending.current || mutation.isPending) return;
      const now = new Date();
      const body = jobInOf(draft, now);
      if (!body) {
        // черновик открыли с середины, а шаг не пройден — вернуться к нему
        if (whatProblems(draft).length > 0) open('what');
        else if (whenProblems(draft, now).length > 0) open('when');
        else if (budgetProblems(draft).length > 0) open('budget');
        return;
      }
      sending.current = true;
      if (editing) {
        update.mutate(
          { jobId: editing.jobId, version: editing.version, body, base: editing.base },
          {
            // правку закрываем, когда мастер уже ушёл с экрана: иначе он начал бы её заново
            // с сохранённой заявкой
            onSuccess: (job) =>
              void router.navigate({ to: managePath(job.id), replace: true }).then(endEdit),
            // заявку изменили в другом месте: мастер показывает её текущую версию
            onError: (error) => {
              if (error instanceof StaleJobError) useDraftStore.getState().edit(error.current);
            },
            onSettled: settled,
          },
        );
        return;
      }
      publish.mutate(
        {
          body,
          key: draft.key,
          directTo: draft.direct?.profileId ?? null,
          rekey: useDraftStore.getState().rekey,
        },
        {
          // итог S21 — сразу по ответу сервера; черновик стирается, когда мастер уже ушёл с
          // экрана (как у правки): ответа DeviceStorage S20d не ждёт. Повтор с тем же черновиком
          // до стирания — тот же ключ: сервер вернёт ту же заявку
          onSuccess: (job) =>
            void router
              .navigate({ to: CREATE_PATHS.done, search: { job: job.id }, replace: true })
              .then(clear),
          onSettled: settled,
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
      <WhoSees draft={draft} direct={!editing && draft.direct ? draft.direct.name : null} />
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

/** Кто что увидит: одна строка, остальное — под «Подробнее». Как устроено на деле: Telegram
 *  выбранный видит в сделке и чате после договорённости, пока он не скрыт в настройках (S43);
 *  телефоном делятся только сами (S54). Прямой запрос (`direct` — имя специалиста) видит и
 *  принимает отклик только этот специалист. */
function WhoSees({ draft, direct }: { draft: JobDraft; direct: string | null }) {
  const { t } = useTranslation('jobs');
  const [open, setOpen] = useState(false);
  const detailsId = useId();
  return (
    <Card tight className="gap-1">
      <div className="flex items-start gap-2.5">
        <Icon name="lock" className="mt-0.5 shrink-0 text-accent" />
        <Text>{t('create.preview.private')}</Text>
      </div>
      {open && <WhoSeesDetails id={detailsId} draft={draft} direct={direct} />}
      <LinkButton
        aria-expanded={open}
        aria-controls={open ? detailsId : undefined}
        onClick={() => setOpen(!open)}
        className="-ml-2 self-start"
      >
        {t(open ? 'create.preview.less' : 'create.preview.more')}
      </LinkButton>
    </Card>
  );
}

function WhoSeesDetails({
  id,
  draft,
  direct,
}: {
  id: string;
  draft: JobDraft;
  direct: string | null;
}) {
  const { t } = useTranslation('jobs');
  const me = useIdentityGetMe();
  const showTelegram = me.data?.privacy.show_telegram ?? true;
  const address = draft.address.trim();
  const chosen = address
    ? t('create.preview.chosenText', { address })
    : t('create.preview.chosenNoAddress');
  return (
    <div
      id={id}
      role="region"
      aria-label={t('create.preview.whoSees')}
      className="flex flex-col gap-3 pt-2"
    >
      <Who
        icon="eye"
        who={
          direct
            ? t('create.preview.everyoneDirect', { name: direct })
            : t('create.preview.everyone')
        }
      >
        {t('create.preview.everyoneText')}
      </Who>
      <Who icon="lock" who={t('create.preview.chosen')}>
        {showTelegram ? `${chosen}${t('create.preview.chosenTelegram')}` : chosen}
      </Who>
      <Who icon="phone" who={t('create.preview.nobody')}>
        {t(showTelegram ? 'create.preview.nobodyPhone' : 'create.preview.nobodyText')}
      </Who>
      {!direct && (
        <Who icon="users" who={t('create.preview.limit', { count: DEFAULT_MAX_RESPONSES })}>
          {t('create.preview.limitText')}
        </Who>
      )}
    </div>
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

/** Правка не сохранилась: заявку изменили в другом месте — мастер уже показывает её текущую
 *  версию, правку вносят заново; версия всё уходила вперёд (412) — открыть заявку заново; иначе —
 *  как публикация. */
function SaveError({ error, onReopen }: { error: unknown; onReopen: () => void }) {
  const { t } = useTranslation('jobs');
  if (error instanceof StaleJobError) {
    return (
      <Banner tone="info" role="status">
        {t('create.preview.changed')}
      </Banner>
    );
  }
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

/** Ошибки ключа идемпотентности — про заголовок запроса, не для человека. */
const KEY_ERRORS: ReadonlySet<string> = new Set([
  'idempotency_key_reused',
  'idempotency_key_required',
  'invalid_idempotency_key',
]);

/** Нет сети, лимит новичка (429 — текст сервера), прочий отказ — с текстом сервера или общим. */
function PublishError({ error }: { error: unknown }) {
  const { t } = useTranslation('jobs');
  const { t: common } = useTranslation();
  const offline = systemStateOf(error).kind === 'offline';
  const detail =
    error instanceof ApiError && error.status < 500 && !KEY_ERRORS.has(error.code)
      ? error.problem.detail
      : null;
  return (
    <Banner tone="danger" role="alert" icon={offline ? 'wifi-off' : 'alert'}>
      {offline ? common('offline.textEmpty') : (detail ?? t('create.preview.publishError'))}
    </Banner>
  );
}
