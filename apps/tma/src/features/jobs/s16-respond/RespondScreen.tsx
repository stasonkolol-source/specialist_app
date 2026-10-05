// S16 Отклик (DEVELOPMENT_PLAN 5.5): шапка заявки — заголовок, бюджет, район и «когда», места;
// сообщение клиенту, цена «Фикс / От / За час / Договорная», «когда смогу», «Контакты откроются
// после договорённости». Пустую форму заполняет основной шаблон, чипы шаблонов вставляют другой,
// «Мои шаблоны» — S57. «Сохранить как шаблон» сохраняет отправленное (название — из сообщения,
// переименовать можно на S57); «Предпросмотр» — так отклик увидит клиент. MainButton «Отправить
// отклик» — с ключом идемпотентности: повтор той же отправки после обрыва сети вернёт тот же
// отклик; 409 и 429 — текстом сервера. Отправлено — «Мои отклики» S17. Свой активный отклик здесь
// же правится: форма с его текстом, «Сохранить изменения».
import type { JobOut, MyResponseOut, ResponseTemplateOut } from '@sosed/api-client';
import { ApiError, getSession, useIdentityGetMe } from '@sosed/api-client';
import type { OfferDraft } from '@sosed/hooks';
import {
  TEMPLATES_MAX,
  emptyOffer,
  isUnavailable,
  offerDraftOf,
  offerIn,
  offerPriceOf,
  offerProblems,
  sameOffer,
  templateTitleOf,
  useCreateTemplate,
  useJob,
  useMyResponse,
  useRespond,
  useResponseTemplates,
  useReviseResponse,
} from '@sosed/hooks';
import { useTranslation } from '@sosed/i18n';
import {
  useBackButton,
  useBottomButtonState,
  useClosingConfirmation,
  usePlatform,
} from '@sosed/platform';
import {
  Avatar,
  Banner,
  Button,
  Card,
  Checkbox,
  Chip,
  Chips,
  Heading,
  Icon,
  LinkButton,
  Price,
  Sheet,
  FieldSkeleton,
  Skeleton,
  SkeletonCard,
  SkeletonText,
  Text,
} from '@sosed/ui-web';
import { useBlocker, useParams, useRouter } from '@tanstack/react-router';
import { useId, useRef, useState } from 'react';

import { JobUnavailable } from '../shared/JobUnavailable.tsx';
import { LoadError } from '../shared/LoadError.tsx';
import { MiniSlots } from '../shared/MiniSlots.tsx';
import { OfferFields } from '../shared/OfferFields.tsx';
import { useStepButton } from '../shared/flow.ts';
import { useBudgetText, useDistrictName, useOfferPrice, useWhenBadge } from '../shared/labels.ts';
import { JOBS_PATHS, jobIdOf } from '../shared/paths.ts';

/** Отклик ещё ждёт решения клиента — его можно поправить. */
const EDITABLE = new Set(['submitted', 'viewed', 'shortlisted']);

export function RespondScreen() {
  const { jobId: raw = '' } = useParams({ strict: false });
  const jobId = jobIdOf(raw);
  const job = useJob(jobId);
  const router = useRouter();
  const mine = job.data?.my_response ?? null;
  const editing = mine !== null && EDITABLE.has(mine.status);
  const response = useMyResponse(editing ? mine.id : null);
  const signedIn = getSession() !== null;
  const templates = useResponseTemplates(signedIn);
  useBackButton(() => {
    if (router.history.canGoBack()) router.history.back();
    else void router.navigate({ to: JOBS_PATHS.job, params: { jobId: raw }, replace: true });
  });

  if (jobId === null || (job.isError && isUnavailable(job.error))) {
    return <JobUnavailable onFeed={() => void router.navigate({ to: JOBS_PATHS.feed })} />;
  }
  const failed = job.error ?? response.error;
  if (failed) {
    return (
      <section className="px-4 pt-6">
        <LoadError
          error={failed}
          onRetry={() => void (job.isError ? job.refetch() : response.refetch())}
          retrying={job.isRefetching || response.isRefetching}
        />
      </section>
    );
  }
  if (!job.data || (editing && !response.data) || (signedIn && templates.isPending)) {
    return <Loading />;
  }
  return (
    <RespondForm
      job={job.data}
      response={editing ? (response.data ?? null) : null}
      templates={templates.data?.items ?? []}
    />
  );
}

function RespondForm({
  job,
  response,
  templates,
}: {
  job: JobOut;
  response: MyResponseOut | null;
  templates: ResponseTemplateOut[];
}) {
  const { t } = useTranslation('jobs');
  const router = useRouter();
  const primary = templates[0];
  const [draft, setDraft] = useState<OfferDraft>(() =>
    response ? offerDraftOf(response) : primary ? offerDraftOf(primary) : emptyOffer(),
  );
  const [saveTemplate, setSaveTemplate] = useState(false);
  const [checked, setChecked] = useState(false);
  const [preview, setPreview] = useState(false);
  const attempt = useRef<{ body: string; key: string } | null>(null);
  const platform = usePlatform();
  // Набранное живёт только в экране: «Назад» молча стирал отклик (UXM-10) — уход с изменённой
  // формой сначала спрашивает; после отправки — уже нет
  const [initial] = useState(draft);
  const done = useRef(false);
  const dirty = JSON.stringify(draft) !== JSON.stringify(initial) || saveTemplate;
  useClosingConfirmation(dirty);
  useBlocker({
    disabled: !dirty,
    enableBeforeUnload: false,
    shouldBlockFn: async () => !done.current && !(await platform.confirm(t('respond.leave'))),
  });
  const send = useRespond();
  const revise = useReviseResponse();
  const createTemplate = useCreateTemplate();
  const mutation = response ? revise : send;
  const problems = checked ? offerProblems(draft) : [];
  const full = templates.length >= TEMPLATES_MAX;
  const fullId = useId();

  const submit = async () => {
    setChecked(true);
    const body = offerIn(draft);
    if (!body || mutation.isPending) return;
    try {
      if (response) {
        await revise.mutateAsync({ jobId: job.id, responseId: response.id, body });
        done.current = true;
        if (router.history.canGoBack()) router.history.back();
        else void router.navigate({ to: JOBS_PATHS.responses, replace: true });
        return;
      }
      // шаблон, вставленный и не изменённый, — отклик «из шаблона» (аналитика, 5.7)
      const template = templates.find((item) => sameOffer(draft, item));
      const sent = { ...body, template_id: template?.id ?? null };
      // тот же ключ — только для того же тела: исправленная форма — новая отправка
      const json = JSON.stringify(sent);
      if (attempt.current?.body !== json)
        attempt.current = { body: json, key: crypto.randomUUID() };
      await send.mutateAsync({ jobId: job.id, body: sent, key: attempt.current.key });
      if (saveTemplate && !full) {
        // шаблон — дополнение к отклику: «Мои отклики» его не ждут, а не сохранился — отклик
        // всё равно ушёл
        void createTemplate
          .mutateAsync({
            key: `${attempt.current.key}:template`,
            body: { ...body, title: templateTitleOf(body.message) },
          })
          .catch(() => undefined);
      }
      done.current = true;
      void router.navigate({ to: JOBS_PATHS.responses, search: { sent: true }, replace: true });
    } catch {
      // ошибка — баннером из mutation.error
    }
  };

  useStepButton({
    text: response ? t('respond.save') : t('respond.send'),
    loading: mutation.isPending,
    onClick: () => void submit(),
  });

  return (
    <section className="flex flex-col gap-3.5 px-4 pt-3 pb-6">
      <JobHeader job={job} editing={response !== null} />
      {mutation.isError && <SendError error={mutation.error} />}
      <OfferFields
        draft={draft}
        onChange={(patch) => setDraft((current) => ({ ...current, ...patch }))}
        problems={problems}
        messageAction={
          <LinkButton onClick={() => void router.navigate({ to: JOBS_PATHS.templates })}>
            {t('respond.myTemplates')}
          </LinkButton>
        }
        messageExtra={
          templates.length > 0 && (
            <Chips label={t('respond.insertTemplate')} wrap>
              {templates.map((template) => (
                <Chip
                  key={template.id}
                  accent={sameOffer(draft, template)}
                  onClick={() => setDraft(offerDraftOf(template))}
                >
                  {template.title}
                </Chip>
              ))}
            </Chips>
          )
        }
      />
      <div className="flex min-h-11 items-center justify-between gap-3">
        {response ? (
          <span />
        ) : (
          // шаблонов уже два — сохранять некуда: галочка приглушена, ниже — где заменить
          <Checkbox
            checked={saveTemplate && !full}
            onChange={setSaveTemplate}
            disabled={full}
            describedBy={full ? fullId : undefined}
            className="min-w-0 flex-1"
          >
            {t('respond.saveTemplate')}
          </Checkbox>
        )}
        <LinkButton className="shrink-0" onClick={() => setPreview(true)}>
          <Icon name="eye" className="mr-1.5" />
          {t('respond.preview')}
        </LinkButton>
      </div>
      {full && !response && (
        <p id={fullId} className="m-0 text-cap text-text2">
          {t('respond.templatesFull', { limit: TEMPLATES_MAX })}
        </p>
      )}
      <Preview open={preview} draft={draft} onClose={() => setPreview(false)} />
    </section>
  );
}

/** Шапка: «Отклик на заявку», заголовок и бюджет, район и «когда», места. */
function JobHeader({ job, editing }: { job: JobOut; editing: boolean }) {
  const { t } = useTranslation('jobs');
  const budgetText = useBudgetText();
  const whenBadge = useWhenBadge();
  const place = useDistrictName(job.city_id, job.district_id);
  const titleId = useId();
  const budget = budgetText(job);
  // «Лиман · сегодня 18–21»: «когда» внутри строки — со строчной
  const label = whenBadge(job).label;
  const when = label.charAt(0).toLowerCase() + label.slice(1);
  return (
    <Card as="section" tight aria-labelledby={titleId}>
      <Text as="span" variant="cap">
        {editing ? t('respond.editCaption') : t('respond.caption')}
      </Text>
      <div className="flex items-start justify-between gap-3">
        <Heading variant="h3" as="h1" id={titleId} className="text-title">
          {job.title}
        </Heading>
        {budget ? (
          <Price>{budget}</Price>
        ) : (
          <span className="shrink-0 text-price text-text2">{t('card.negotiable')}</span>
        )}
      </div>
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1.5">
        <span className="flex min-w-0 items-center gap-1.5 text-cap text-text2">
          <Icon name="pin" size={16} className="shrink-0" />
          <span className="truncate">{[place, when].filter(Boolean).join(' · ')}</span>
        </span>
        <MiniSlots job={job} />
      </div>
    </Card>
  );
}

/** 409, 429 и 422 — текстом сервера на языке интерфейса; сеть и 5xx — «повторите». */
function SendError({ error }: { error: unknown }) {
  const { t } = useTranslation('jobs');
  const detail = error instanceof ApiError && error.status < 500 ? error.problem.detail : null;
  return (
    <Banner tone="danger" role="alert">
      {detail ?? t('respond.error')}
    </Banner>
  );
}

/** «Так отклик увидит клиент»: имя, сообщение, цена и «когда смогу». */
function Preview({
  open,
  draft,
  onClose,
}: {
  open: boolean;
  draft: OfferDraft;
  onClose: () => void;
}) {
  const { t } = useTranslation('jobs');
  const { t: common } = useTranslation();
  const me = useIdentityGetMe({ query: { enabled: open } });
  const offerPrice = useOfferPrice();
  const price = offerPriceOf(draft);
  const button = useBottomButtonState('main');
  const name = me.data?.display_name ?? t('respond.you');
  // «Назад» Telegram сначала закрывает шторку
  useBackButton(open ? onClose : null);
  return (
    <Sheet
      open={open}
      title={t('respond.previewTitle')}
      onClose={onClose}
      closeLabel={common('action.close')}
    >
      <Card as="article" tight>
        <div className="flex items-center gap-3">
          <Avatar name={name} />
          <span className="text-title">{name}</span>
        </div>
        <Text className="whitespace-pre-line">{draft.message.trim()}</Text>
        <div className="flex flex-wrap items-center justify-between gap-2">
          {price && <Price>{offerPrice(price)}</Price>}
          {draft.when.trim() && (
            <Text as="span" variant="cap">
              {draft.when.trim()}
            </Text>
          )}
        </div>
      </Card>
      <Banner tone="info" icon="clock">
        {t('respond.previewNote')}
      </Banner>
      <Button variant="secondary" full onClick={onClose}>
        {common('action.close')}
      </Button>
      {/* в браузере AppShell рисует «Отправить отклик» поверх шторки — место под кнопку */}
      {!button.native && <div className="h-19" aria-hidden="true" />}
    </Sheet>
  );
}

function Loading() {
  return (
    <section className="flex flex-col gap-3.5 px-4 pt-3 pb-6" aria-busy="true">
      {/* заявка: раздел, название и бюджет, место и места */}
      <SkeletonCard tight>
        <SkeletonText size="cap" className="w-1/3" />
        <div className="flex items-start justify-between gap-3">
          <SkeletonText size="title" className="w-3/5" />
          <SkeletonText size="title" className="w-20" />
        </div>
        <SkeletonText size="cap" className="w-1/2" />
      </SkeletonCard>
      {/* сообщение, вид цены и цена */}
      <FieldSkeleton tall />
      <Skeleton screen radius="field" className="h-10 w-full" />
      <FieldSkeleton />
    </section>
  );
}
