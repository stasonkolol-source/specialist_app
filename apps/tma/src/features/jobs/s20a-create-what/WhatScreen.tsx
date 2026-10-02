// S20a «Что нужно сделать?», шаг 1 из 4 (DEVELOPMENT_PLAN 5.2): коротко о задаче; категория —
// подобранная по тексту (`/suggest`, пока человек не выбрал сам) или выбранная в шторке; подробности
// и до шести фото (purpose=job). Телефон и адрес здесь не пишут: адрес — на S20b, его увидит только
// выбранный исполнитель. CTA с категорией и названием (S03, S05, S09) начинают с них новый черновик.
import type { CategoryOut } from '@sosed/api-client';
import type { DraftPhoto, JobDraft, UploadItem } from '@sosed/hooks';
import {
  JOB_DESCRIPTION_MAX,
  JOB_PHOTOS_MAX,
  JOB_TITLE_MAX,
  JOB_TITLE_MIN,
  useCategories,
  useMediaUploads,
  useSuggest,
  whatProblems,
} from '@sosed/hooks';
import { useLocale, useTranslation } from '@sosed/i18n';
import { usePlatform } from '@sosed/platform';
import {
  AddTile,
  Banner,
  Chip,
  Field,
  IconButton,
  Input,
  LinkButton,
  Photo,
  Row,
  Sheet,
  Text,
  Textarea,
  UploadTile,
} from '@sosed/ui-web';
import { useSearch } from '@tanstack/react-router';
import { useEffect, useId, useState } from 'react';

import { categoryPath, findCategory } from '../shared/categories.ts';
import { useDebounced } from '../shared/debounce.ts';
import { useJobDraft } from '../shared/draft.ts';
import { useCreateFlow, useStepButton } from '../shared/flow.ts';
import { CREATE_PATHS } from '../shared/paths.ts';
import { mediaTransport } from '../shared/uploads.ts';
import { WizardHeader } from '../shared/WizardHeader.tsx';

/** Подбор категории — когда человек перестал печатать. */
const SUGGEST_DELAY_MS = 400;
const PHOTO_TILE = 'size-18';

export function WhatScreen() {
  const { draft, patch } = useJobDraft();
  const flow = useCreateFlow('what', draft);
  if (!draft) return null;
  return <WhatForm draft={draft} patch={patch} next={flow.next} />;
}

function WhatForm({
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
  const locale = useLocale();
  const search = useSearch({ from: CREATE_PATHS.what });
  const tree = useCategories(locale).data ?? [];
  const [picking, setPicking] = useState(false);
  // незаполненное подсвечиваем после первого «Далее»
  const [checked, setChecked] = useState(false);
  const photos = usePhotos(draft, patch);

  // CTA с категорией и названием: новый черновик начинается с них, начатый — не трогаем
  useEffect(() => {
    if (draft.title || draft.categoryId !== null) return;
    if (search.title === undefined && search.category === undefined) return;
    patch({
      title: search.title ?? '',
      categoryId: search.category ?? null,
      categoryChosen: search.category !== undefined,
    });
  }, [draft.title, draft.categoryId, search.title, search.category, patch]);

  // категория по тексту, пока человек её не выбрал сам
  const settled = useDebounced(draft.title.trim(), SUGGEST_DELAY_MS);
  const suggested = useSuggest(settled, locale).data?.items[0];
  useEffect(() => {
    if (draft.categoryChosen || !suggested || suggested.category_id === draft.categoryId) return;
    patch({ categoryId: suggested.category_id, categoryName: suggested.name });
  }, [draft.categoryChosen, draft.categoryId, suggested, patch]);

  const problems = whatProblems(draft);
  const label =
    draft.categoryId !== null
      ? (categoryPath(tree, draft.categoryId) ?? draft.categoryName)
      : null;
  useStepButton({
    text: common('action.next'),
    loading: photos.uploading,
    onClick: () => {
      setChecked(true);
      if (problems.length === 0 && !photos.uploading) next();
    },
  });

  const choose = (category: CategoryOut) => {
    patch({ categoryId: category.id, categoryName: category.name, categoryChosen: true });
    setPicking(false);
  };

  return (
    <section className="flex flex-col gap-4 px-4 pt-3 pb-6">
      <WizardHeader step={1} title={t('create.what.title')} />
      <Field
        label={t('create.what.summary')}
        error={
          checked && problems.includes('title')
            ? t('create.what.summaryShort', { min: JOB_TITLE_MIN })
            : undefined
        }
      >
        <Input
          value={draft.title}
          maxLength={JOB_TITLE_MAX}
          placeholder={t('create.what.summaryPlaceholder')}
          onChange={(event) => patch({ title: event.target.value })}
        />
      </Field>
      <CategoryField
        label={label}
        chosen={draft.categoryChosen}
        missing={checked && problems.includes('category')}
        onPick={() => setPicking(true)}
      />
      <Field label={t('create.what.details')} hint={t('create.what.detailsHint')}>
        <Textarea
          value={draft.description}
          maxLength={JOB_DESCRIPTION_MAX}
          rows={4}
          placeholder={t('create.what.detailsPlaceholder')}
          onChange={(event) => patch({ description: event.target.value })}
        />
      </Field>
      <PhotosField photos={photos} />
      <Banner tone="info" icon="lock">
        {t('create.what.privacy')}
      </Banner>
      <CategoryPicker
        open={picking}
        tree={tree}
        onClose={() => setPicking(false)}
        onChoose={choose}
      />
    </section>
  );
}

function CategoryField({
  label,
  chosen,
  missing,
  onPick,
}: {
  label: string | null;
  chosen: boolean;
  missing: boolean;
  onPick: () => void;
}) {
  const { t } = useTranslation('jobs');
  const titleId = useId();
  return (
    <div className="flex flex-col gap-1.5" role="group" aria-labelledby={titleId}>
      <span id={titleId} className="text-sm font-semibold">
        {t('create.what.category')}
      </span>
      {label ? (
        // длинное «Раздел → Услуга» не выталкивает «Изменить» за край — переносит его ниже
        <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
          <Chip accent icon="wrench" onClick={onPick}>
            {label}
          </Chip>
          <LinkButton onClick={onPick} className="-mr-2">
            {t('create.what.change')}
          </LinkButton>
        </div>
      ) : (
        <div className="self-start">
          <Chip icon="grid" onClick={onPick}>
            {t('create.what.pick')}
          </Chip>
        </div>
      )}
      <Text variant="cap" className={missing ? 'text-danger' : undefined}>
        {label
          ? t(chosen ? 'create.what.chosen' : 'create.what.suggested')
          : t('create.what.missing')}
      </Text>
    </div>
  );
}

/** Шторка выбора: разделы, в разделе — его услуги (заявка — в лист каталога). */
function CategoryPicker({
  open,
  tree,
  onClose,
  onChoose,
}: {
  open: boolean;
  tree: readonly CategoryOut[];
  onClose: () => void;
  onChoose: (category: CategoryOut) => void;
}) {
  const { t } = useTranslation('jobs');
  const { t: common } = useTranslation();
  const [sectionId, setSectionId] = useState<number | null>(null);
  const section = sectionId !== null ? findCategory(tree, sectionId) : null;
  const rows = section ? section.children : tree;
  const close = () => {
    setSectionId(null);
    onClose();
  };
  return (
    <Sheet
      open={open}
      title={section ? section.name : t('create.what.pickerTitle')}
      onClose={close}
      closeLabel={common('action.close')}
    >
      <div className="-mx-4 flex flex-col">
        {section && (
          <Row
            icon="chev-left"
            title={t('create.what.pickerBack')}
            onClick={() => setSectionId(null)}
          />
        )}
        {rows.map((node) => (
          <Row
            key={node.id}
            title={node.name}
            chevron={node.children.length > 0}
            onClick={() => {
              if (node.children.length > 0) setSectionId(node.id);
              else {
                setSectionId(null);
                onChoose(node);
              }
            }}
          />
        ))}
      </div>
    </Sheet>
  );
}

interface Photos {
  saved: readonly DraftPhoto[];
  items: readonly UploadItem[];
  room: number;
  uploading: boolean;
  add: (files: File[]) => void;
  retry: (key: string) => void;
  cancel: (key: string) => void;
  remove: (id: string) => void;
}

/** Фото заявки: загруженные — в черновике, загружаемые — здесь, пока экран открыт. */
function usePhotos(draft: JobDraft, patch: (patch: Partial<JobDraft>) => void): Photos {
  const platform = usePlatform();
  const room = JOB_PHOTOS_MAX - draft.photos.length;
  const uploads = useMediaUploads({ purpose: 'job', transport: mediaTransport, max: room });
  // загруженный файл переезжает в черновик: он переживёт уход с шага и перезапуск
  useEffect(() => {
    const done = uploads.items.filter((item) => item.status === 'uploaded' && item.media);
    if (done.length === 0) return;
    const added = done.flatMap((item) => (item.media ? [photoOf(item.media)] : []));
    patch({ photos: [...draft.photos, ...added] });
    for (const item of done) uploads.forget(item.key);
  }, [uploads, draft.photos, patch]);
  return {
    saved: draft.photos,
    items: uploads.items.filter((item) => item.status !== 'uploaded'),
    room,
    uploading: uploads.uploading,
    add: (files) => {
      const left = uploads.add(files);
      if (left > 0) platform.haptics.notification('warning');
      else platform.haptics.selection();
    },
    retry: uploads.retry,
    cancel: uploads.remove,
    remove: (id) => patch({ photos: draft.photos.filter((photo) => photo.id !== id) }),
  };
}

function photoOf(media: NonNullable<UploadItem['media']>): DraftPhoto {
  const thumb = media.variants.find((variant) => variant.name === 'thumb');
  return { id: media.id, thumb: thumb?.url ?? media.preview_url };
}

function PhotosField({ photos }: { photos: Photos }) {
  const { t } = useTranslation('jobs');
  const { t: common } = useTranslation();
  const titleId = useId();
  return (
    <div className="flex flex-col gap-2" role="group" aria-labelledby={titleId}>
      <span id={titleId} className="text-sm font-semibold">
        {t('create.what.photos')}{' '}
        <span className="font-normal text-text2">{t('create.what.photosOptional')}</span>
      </span>
      <div className="flex flex-wrap gap-2">
        {photos.saved.map((photo, index) => (
          <div key={photo.id} className={`relative ${PHOTO_TILE}`}>
            <Photo
              src={photo.thumb ?? undefined}
              alt={t('create.what.photo', { number: index + 1 })}
              className={PHOTO_TILE}
            />
            <IconButton
              icon="x"
              label={common('photo.remove')}
              onClick={() => photos.remove(photo.id)}
              className="absolute -top-2 -right-2 size-7"
            />
          </div>
        ))}
        {photos.items.map((item) =>
          item.status === 'failed' ? (
            <UploadTile
              key={item.key}
              state="failed"
              compact
              label={common(item.retryable ? 'photo.uploadFailed' : 'photo.rejected')}
              onRetry={item.retryable ? () => photos.retry(item.key) : undefined}
              retryLabel={common('action.retry')}
              onRemove={() => photos.cancel(item.key)}
              removeLabel={common('photo.remove')}
              className={PHOTO_TILE}
            />
          ) : (
            <UploadTile
              key={item.key}
              state="uploading"
              compact
              progress={item.progress}
              label={common('photo.uploading', { percent: Math.round(item.progress * 100) })}
              className={PHOTO_TILE}
            />
          ),
        )}
        {photos.room - photos.items.length > 0 && (
          <AddTile
            label={common('photo.add')}
            icon="camera"
            accept="image/*"
            multiple
            onFiles={photos.add}
            className={PHOTO_TILE}
          />
        )}
      </div>
    </div>
  );
}
