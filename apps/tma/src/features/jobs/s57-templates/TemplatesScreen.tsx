// S57 Шаблоны откликов (DEVELOPMENT_PLAN 5.5): до двух шаблонов «сообщение + цена + когда смогу» —
// оба кнопками в уведомлениях бота (5.7), первый — «Основной»: его S16 подставляет сразу.
// «Изменить» и MainButton «Новый шаблон» открывают шторку с полями; «Сделать основным» ставит
// шаблон первым. Третий шаблон — «Шаблонов уже 2 — удалите один» (сервер ответил бы 409
// `response_templates_full`). На макете — «3 из 10»; по плану и PRODUCT шаблонов два.
import type { ResponseTemplateOut } from '@sosed/api-client';
import { ApiError } from '@sosed/api-client';
import {
  TEMPLATES_MAX,
  TEMPLATE_TITLE_MAX,
  emptyOffer,
  offerDraftOf,
  offerIn,
  offerProblems,
  useCreateTemplate,
  useDeleteTemplate,
  useResponseTemplates,
  useUpdateTemplate,
} from '@sosed/hooks';
import type { OfferDraft } from '@sosed/hooks';
import { useTranslation } from '@sosed/i18n';
import { useBackButton, useBottomButtonState, usePlatform } from '@sosed/platform';
import {
  Badge,
  Banner,
  Button,
  Card,
  EmptyState,
  Field,
  Heading,
  Icon,
  Input,
  LinkButton,
  Sheet,
  Skeleton,
  Text,
} from '@sosed/ui-web';
import { useRouter } from '@tanstack/react-router';
import { useId, useRef, useState } from 'react';

import { LoadError } from '../shared/LoadError.tsx';
import { OfferFields } from '../shared/OfferFields.tsx';
import { useStepButton } from '../shared/flow.ts';
import { useOfferPrice } from '../shared/labels.ts';
import { JOBS_PATHS } from '../shared/paths.ts';

/** Шторка: новый шаблон или правка этого. */
type Editing = ResponseTemplateOut | 'new' | null;

export function TemplatesScreen() {
  const { t } = useTranslation('jobs');
  const router = useRouter();
  const templates = useResponseTemplates();
  const update = useUpdateTemplate();
  const [editing, setEditing] = useState<Editing>(null);
  const [fullShown, setFullShown] = useState(false);
  useBackButton(() => {
    if (router.history.canGoBack()) router.history.back();
    else void router.navigate({ to: JOBS_PATHS.responses, replace: true });
  });

  const items = templates.data?.items ?? [];
  const limit = templates.data?.limit ?? TEMPLATES_MAX;
  const full = items.length >= limit;

  let content;
  if (templates.isError) {
    content = (
      <LoadError
        error={templates.error}
        onRetry={() => void templates.refetch()}
        retrying={templates.isRefetching}
      />
    );
  } else if (!templates.data) {
    content = (
      <>
        <Skeleton radius="card" className="h-32 w-full" />
        <Skeleton radius="card" className="h-32 w-full" />
      </>
    );
  } else if (items.length === 0) {
    content = (
      <EmptyState as="h2" icon="file" title={t('templates.emptyTitle')}>
        {t('templates.emptyText')}
      </EmptyState>
    );
  } else {
    content = (
      <>
        {items.map((template) => (
          <TemplateCard
            key={template.id}
            template={template}
            onEdit={() => setEditing(template)}
            onPrimary={() => update.mutate({ templateId: template.id, body: { primary: true } })}
          />
        ))}
        <Text variant="cap" className="text-center">
          {t('templates.count', { count: items.length, limit })}
        </Text>
      </>
    );
  }

  return (
    <section className="flex flex-col gap-3 px-4 pt-3 pb-6">
      <div className="flex flex-col gap-1">
        <Heading variant="h2" as="h1">
          {t('templates.title')}
        </Heading>
        <Text variant="cap">{t('templates.lead')}</Text>
      </div>
      {fullShown && full && (
        <Banner tone="warn" role="alert">
          {t('templates.full', { limit })}
        </Banner>
      )}
      {update.isError && (
        <Banner tone="danger" role="alert">
          {t('templates.error')}
        </Banner>
      )}
      {content}
      {/* MainButton — у шторки, пока она открыта: у экрана одна нижняя кнопка */}
      {editing === null && templates.data && (
        <NewButton onClick={() => (full ? setFullShown(true) : setEditing('new'))} />
      )}
      {editing !== null && (
        <TemplateSheet
          key={editing === 'new' ? 'new' : editing.id}
          template={editing === 'new' ? null : editing}
          onClose={() => setEditing(null)}
        />
      )}
    </section>
  );
}

function NewButton({ onClick }: { onClick: () => void }) {
  const { t } = useTranslation('jobs');
  useStepButton({ text: t('templates.new'), onClick });
  return null;
}

function TemplateCard({
  template,
  onEdit,
  onPrimary,
}: {
  template: ResponseTemplateOut;
  onEdit: () => void;
  onPrimary: () => void;
}) {
  const { t } = useTranslation('jobs');
  const offerPrice = useOfferPrice();
  const titleId = useId();
  const price =
    template.price.type === 'negotiable' ? t('card.negotiable') : offerPrice(template.price);
  const meta = [price, template.availability_note].filter(Boolean).join(' · ');
  return (
    <Card as="article" tight aria-labelledby={titleId}>
      <div className="flex items-center justify-between gap-3">
        <span className="flex min-w-0 items-center gap-2">
          <span id={titleId} className="truncate font-semibold">
            {template.title}
          </span>
          {template.primary ? (
            <Badge tone="ok">{t('templates.primary')}</Badge>
          ) : (
            <Badge tone="info" icon="send">
              {t('templates.inBot')}
            </Badge>
          )}
        </span>
        <Button variant="outline" size="sm" aria-describedby={titleId} onClick={onEdit}>
          {t('templates.edit')}
        </Button>
      </div>
      <Text variant="sm" className="whitespace-pre-line">
        {template.message}
      </Text>
      <div className="flex flex-wrap items-center justify-between gap-x-3">
        <span className="flex min-w-0 items-center gap-1.5 text-cap text-text2">
          <Icon name="wallet" size={16} className="shrink-0" />
          <span>{meta}</span>
        </span>
        {!template.primary && (
          <LinkButton className="-mr-2" aria-describedby={titleId} onClick={onPrimary}>
            {t('templates.makePrimary')}
          </LinkButton>
        )}
      </div>
    </Card>
  );
}

/** Шторка шаблона: название и поля предложения; MainButton «Сохранить шаблон», «Удалить». */
function TemplateSheet({
  template,
  onClose,
}: {
  template: ResponseTemplateOut | null;
  onClose: () => void;
}) {
  const { t } = useTranslation('jobs');
  const { t: common } = useTranslation();
  const platform = usePlatform();
  const button = useBottomButtonState('main');
  const [title, setTitle] = useState(template?.title ?? '');
  const [draft, setDraft] = useState<OfferDraft>(() =>
    template ? offerDraftOf(template) : emptyOffer(),
  );
  const [checked, setChecked] = useState(false);
  const attempt = useRef<{ body: string; key: string } | null>(null);
  const create = useCreateTemplate();
  const update = useUpdateTemplate();
  const remove = useDeleteTemplate();
  const failed = create.error ?? update.error ?? remove.error;
  const problems = checked ? offerProblems(draft) : [];
  const noTitle = checked && !title.trim();

  const save = async () => {
    setChecked(true);
    const body = offerIn(draft);
    const name = title.trim();
    if (!body || !name || create.isPending || update.isPending) return;
    try {
      if (template) {
        await update.mutateAsync({ templateId: template.id, body: { ...body, title: name } });
      } else {
        const sent = { ...body, title: name };
        const json = JSON.stringify(sent);
        if (attempt.current?.body !== json)
          attempt.current = { body: json, key: crypto.randomUUID() };
        await create.mutateAsync({ key: attempt.current.key, body: sent });
      }
      onClose();
    } catch {
      // ошибка — баннером
    }
  };
  const drop = async () => {
    if (!template) return;
    if (!(await platform.confirm(t('templates.deleteConfirm', { title: template.title })))) return;
    try {
      await remove.mutateAsync(template.id);
      onClose();
    } catch {
      // ошибка — баннером
    }
  };

  useStepButton({
    text: t('templates.save'),
    loading: create.isPending || update.isPending,
    onClick: () => void save(),
  });
  useBackButton(onClose);

  const detail = failed instanceof ApiError && failed.status < 500 ? failed.problem.detail : null;
  return (
    <Sheet
      open
      title={template ? t('templates.sheetEdit') : t('templates.new')}
      onClose={onClose}
      closeLabel={common('action.close')}
    >
      {failed && (
        <Banner tone="danger" role="alert">
          {detail ?? t('templates.error')}
        </Banner>
      )}
      <Field label={t('templates.name')} error={noTitle ? t('templates.missingName') : undefined}>
        <Input
          maxLength={TEMPLATE_TITLE_MAX}
          value={title}
          placeholder={t('templates.namePlaceholder')}
          onChange={(event) => setTitle(event.target.value)}
        />
      </Field>
      <OfferFields
        draft={draft}
        onChange={(patch) => setDraft((current) => ({ ...current, ...patch }))}
        problems={problems}
      />
      {template && (
        <Button variant="danger" icon="trash" full onClick={() => void drop()}>
          {t('templates.delete')}
        </Button>
      )}
      {/* в браузере AppShell рисует «Сохранить шаблон» поверх шторки — место под кнопку */}
      {!button.native && <div className="h-19" aria-hidden="true" />}
    </Sheet>
  );
}
