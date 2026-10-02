// Разделы галереи для компонентов 0.19b и плиток загрузки 2.1.
import { useFormat, useTranslation } from '@sosed/i18n';
import type { ReactNode } from 'react';
import { useEffect, useState } from 'react';

import {
  AddTile,
  Avatar,
  AvatarStack,
  Badge,
  Banner,
  Button,
  Card,
  Chip,
  Chips,
  EmptyState,
  Field,
  Group,
  HStack,
  IconButton,
  Input,
  JobCard,
  MapPreview,
  Option,
  PickerButton,
  Photo,
  Price,
  ProgressBar,
  Row,
  SearchField,
  Segmented,
  SegmentedNav,
  Sheet,
  Skeleton,
  SpecialistCard,
  Stack,
  Stars,
  Steps,
  Switch,
  Textarea,
  Tile,
  Tiles,
  Toast,
  UploadTile,
} from '../src/index.ts';

/** Карточки S05 — как SPEC §4: «коротко о себе» и районы — данные, не строки интерфейса. */
const CARDS = [
  { headline: 'Электрик · мелкий ремонт · люстры', district: 'Лиман', km: 1_500, rating: 4.9 },
  { headline: 'Сборка мебели · полки · карнизы', district: 'Детелинара', km: 3_000, rating: null },
] as const;

/** Заявки S13 — как SPEC §4 (JOBS): заголовки, категории и районы — данные. */
const JOB_CARDS = [
  {
    title: 'Течёт смеситель на кухне',
    category: 'Сантехника',
    description: 'Капает из-под крана. Нужно заменить картридж или смеситель целиком.',
    district: 'Центр',
    km: 2_000,
  },
  {
    title: 'Повесить люстру',
    category: 'Люстры',
    description: 'Потолок бетонный, крюк есть. Люстра на 5 рожков, нужно подключить.',
    district: 'Лиман',
    km: 1_200,
  },
] as const;

const PEOPLE = [
  { name: 'Алексей Морозов', palette: 1 },
  { name: 'Дмитрий Соколов', palette: 2 },
  { name: 'Никола Петрович', palette: 3 },
] as const;

export function Section({ id, name, children }: { id: string; name: string; children: ReactNode }) {
  return (
    <section
      data-gallery={id}
      aria-labelledby={`g-${id}`}
      className="flex flex-col gap-3 bg-bg2 py-4"
    >
      <h2 id={`g-${id}`} className="m-0 px-4 text-section text-text2 uppercase">
        {name}
      </h2>
      <div className="px-4">{children}</div>
    </section>
  );
}

export function MoreSections() {
  const { t } = useTranslation();
  const catalog = useTranslation('catalog').t;
  const format = useFormat();
  const [urgency, setUrgency] = useState<'asap' | 'today' | 'this_week'>('today');
  const [budget, setBudget] = useState<'fixed' | 'range'>('fixed');
  const [langs, setLangs] = useState(true);
  const [notify, setNotify] = useState(true);
  const [stars, setStars] = useState(4);
  const negotiable = t('price.negotiable').replace(/^./u, (letter) => letter.toUpperCase());

  return (
    <>
      <Section id="group" name="Group · Row · Switch">
        <Group>
          <Row
            icon="bell"
            title={t('settings.notifications')}
            trailing={
              <Switch checked={notify} onChange={setNotify} label={t('settings.notifications')} />
            }
          />
          <Row
            icon="languages"
            title={t('settings.language')}
            subtitle={t('app.miniApp')}
            chevron
            href="#lang"
          />
          <Row
            leading={<Avatar name={PEOPLE[0].name} palette={1} size="sm" />}
            title={PEOPLE[0].name}
            subtitle={t('count.reviews', { count: 37 })}
            trailing={<Badge tone="ok">{t('count.firstResponder')}</Badge>}
          />
        </Group>
      </Section>

      <Section id="tiles" name="Tiles · Tile">
        <Tiles>
          <Tile icon="wrench" palette={1} label={t('category.handyman')} href="#c1" />
          <Tile icon="scissors" palette={4} label={t('category.beauty')} href="#c2" />
          <Tile icon="broom" palette={2} label={t('category.cleaning')} href="#c3" />
          <Tile icon="truck" palette={3} label={t('category.moving')} href="#c4" />
          <Tile icon="book" palette={5} label={t('category.tutors')} href="#c5" />
          <Tile icon="grid" label={t('category.all')} href="#c6" />
        </Tiles>
      </Section>

      <Section id="chips" name="Chips · Chip · AvatarStack · Price">
        <Stack gap={12}>
          <Chips wrap label={t('action.search')}>
            <Chip selected>{t('urgency.today')}</Chip>
            <Chip icon="zap">{t('urgency.asap')}</Chip>
            <Chip accent count={3}>
              {t('glossary.gig')}
            </Chip>
            <Chip>{t('urgency.this_week')}</Chip>
          </Chips>
          <HStack between>
            <AvatarStack people={[...PEOPLE]} label={t('count.responses', { count: 3 })} />
            <Price>{format.price({ type: 'from', min: 200_000, unit: 'visit' })}</Price>
          </HStack>
          <Price large>{format.money(350_000)}</Price>
        </Stack>
      </Section>

      <Section id="photo" name="Photo">
        <HStack gap={8}>
          <Photo alt={t('photo.work')} className="h-28 w-28" />
          <Photo alt={t('photo.work')} video className="h-28 w-28" />
          <Photo alt={t('photo.work')} className="h-28 flex-1" />
        </HStack>
      </Section>

      <Section id="upload" name="AddTile · UploadTile">
        <UploadDemo />
      </Section>

      <Section id="form" name="SearchField · Field · Input · PickerButton · Textarea">
        <Stack gap={16}>
          <SearchField
            label={t('action.search')}
            placeholder={t('search.placeholder')}
            trailing={<IconButton icon="sliders" label={t('action.search')} plain />}
          />
          <Field label={t('form.description')} error={t('form.required')}>
            <Textarea placeholder={t('search.placeholder')} />
          </Field>
          <Field label={t('form.budget')} hint={t('form.budgetHint')}>
            <Input inputMode="numeric" defaultValue={format.number(5_000)} suffix="RSD" />
          </Field>
          <Field label={t('category.handyman')}>
            <PickerButton icon="pin" onClick={() => undefined}>
              {t('settings.language')}
            </PickerButton>
          </Field>
          <Field label={t('settings.language')}>
            <Input icon="lock" defaultValue={t('category.handyman')} />
          </Field>
        </Stack>
      </Section>

      <Section id="map" name="MapPreview">
        <MapPreview
          label={t('category.handyman')}
          caption={t('search.placeholder')}
          description={t('settings.language')}
        />
      </Section>

      <Section id="choice" name="Segmented · Option">
        <Stack gap={12}>
          <Segmented
            label={t('form.budget')}
            value={urgency}
            onChange={setUrgency}
            options={[
              { value: 'asap', label: t('urgency.asap'), icon: 'zap' },
              { value: 'today', label: t('urgency.today') },
              { value: 'this_week', label: t('urgency.this_week') },
            ]}
          />
          <div role="radiogroup" aria-label={t('form.budget')} className="flex flex-col gap-2">
            <Option
              title={format.money(500_000)}
              description={t('unit.work')}
              checked={budget === 'fixed'}
              onChange={() => setBudget('fixed')}
            />
            <Option
              title={t('price.negotiable')}
              checked={budget === 'range'}
              onChange={() => setBudget('range')}
            />
          </div>
          <Option
            kind="checkbox"
            icon="languages"
            title={t('settings.language')}
            checked={langs}
            onChange={setLangs}
          />
        </Stack>
      </Section>

      <Section id="progress" name="Steps · ProgressBar · Stars">
        <Stack gap={16}>
          <Steps total={5} current={2} label={t('form.step', { current: 2, total: 5 })} />
          <ProgressBar value={60} label={t('form.step', { current: 3, total: 5 })} />
          <Stars
            value={stars}
            onChange={setStars}
            label={t('rating.label')}
            starLabel={(n) => t('rating.star', { count: n })}
          />
          <Stars
            value={5}
            label={t('rating.star', { count: 5 })}
            starLabel={(n) => t('rating.star', { count: n })}
          />
        </Stack>
      </Section>

      <Section id="feedback" name="Banner · EmptyState · Toast · Skeleton">
        <Stack gap={12}>
          <Banner tone="warn">{t('safety.prepayment')}</Banner>
          <Banner tone="ok">{t('status.deal.agreed')}</Banner>
          <Banner tone="info">{t('status.job.pending_moderation')}</Banner>
          <Banner tone="danger">{t('form.required')}</Banner>
          <EmptyState
            icon="jobs"
            title={t('empty.jobsTitle')}
            action={<Button>{t('action.publish')}</Button>}
          >
            {t('empty.jobsText')}
          </EmptyState>
          <Toast position="static">{t('toast.saved')}</Toast>
          <Card>
            <HStack gap={12}>
              <Skeleton round className="size-12" />
              <Stack gap={8} className="flex-1">
                <Skeleton className="h-4 w-3/4" />
                <Skeleton className="h-4 w-1/2" />
              </Stack>
            </HStack>
          </Card>
        </Stack>
      </Section>

      <Section id="specialist" name="SpecialistCard">
        <Stack gap={12}>
          {CARDS.map((card, index) => {
            const person = PEOPLE[index] ?? PEOPLE[0];
            return (
              <SpecialistCard
                key={person.name}
                name={person.name}
                headline={card.headline}
                rating={card.rating === null ? null : format.rating(card.rating)}
                reviews={catalog('results.reviews', { count: 37 })}
                newLabel={t('rating.new')}
                meta={[`${card.district}, ${format.distance(card.km)}`, 'ru, sr']}
                badges={
                  index === 0
                    ? [
                        {
                          label: catalog('results.todayUntil', { time: '20:00' }),
                          tone: 'ok',
                          dot: true,
                        },
                        { label: catalog('results.phoneVerified'), tone: 'info', icon: 'shield' },
                      ]
                    : []
                }
                price={format.price({ type: 'from', min: 200_000 })}
                href="#s08"
              />
            );
          })}
        </Stack>
      </Section>

      <Section id="job" name="JobCard · SegmentedNav">
        <Stack gap={12}>
          <SegmentedNav
            label={t('nav.sections')}
            current="jobs"
            items={[
              { id: 'home', label: t('nav.home'), href: '#home' },
              { id: 'jobs', label: t('nav.jobs'), href: '#jobs' },
              { id: 'messages', label: t('nav.messages'), href: '#messages' },
            ]}
          />
          <JobCard
            title={JOB_CARDS[0].title}
            budget={negotiable}
            negotiable
            badges={[
              { label: t('urgency.asap'), tone: 'urgent', icon: 'zap' },
              { label: JOB_CARDS[0].category, tone: 'mute' },
            ]}
            time={t('time.minutesAgo', { count: 5 })}
            description={JOB_CARDS[0].description}
            place={`${JOB_CARDS[0].district}, ${format.distance(JOB_CARDS[0].km)}`}
            slots={{ taken: 4, total: 5, label: t('count.responsesOf', { count: 4, total: 5 }) }}
            href="#s15"
          />
          <JobCard
            title={JOB_CARDS[1].title}
            budget={format.money(500_000)}
            badges={[
              { label: t('urgency.today'), tone: 'info', icon: 'clock' },
              { label: JOB_CARDS[1].category, tone: 'mute' },
            ]}
            time={t('time.minutesAgo', { count: 15 })}
            description={JOB_CARDS[1].description}
            photos={[{ src: '' }, { src: '' }]}
            photoLabel={() => t('photo.work')}
            place={`${JOB_CARDS[1].district}, ${format.distance(JOB_CARDS[1].km)}`}
            slots={{ taken: 3, total: 5, label: t('count.responsesOf', { count: 3, total: 5 }) }}
          />
        </Stack>
      </Section>

      <Section id="sheet" name="Sheet">
        {/* transform делает рамку точкой отсчёта для fixed: шторка — внутри раздела, а не окна */}
        <div className="relative h-96 transform-gpu overflow-hidden rounded-card bg-bg2">
          <Sheet
            open
            title={catalog('filters.title')}
            closeLabel={catalog('filters.close')}
            onClose={() => {}}
          >
            <Chips wrap label={catalog('filters.districts')}>
              <Chip selected>{catalog('filters.wholeCity')}</Chip>
              <Chip>{PEOPLE[0].name}</Chip>
            </Chips>
            <Group className="border border-line">
              <Row
                title={catalog('filters.availableToday')}
                trailing={
                  <Switch label={catalog('filters.availableToday')} checked onChange={() => {}} />
                }
              />
            </Group>
          </Sheet>
        </div>
      </Section>
    </>
  );
}

interface DemoUpload {
  key: number;
  file: File;
  progress: number;
}

const DEMO_STEP = 0.1;
const DEMO_TICK_MS = 200;

/**
 * Плитки S37 (сетка, 114 px) и S20a (ряд, 72 px). Выбранные файлы «грузятся» понарошку: API
 * в галерее нет, настоящая загрузка — useMediaUploads (packages/hooks). Статичные плитки
 * показывают состояния для скриншотов.
 */
function UploadDemo() {
  const { t } = useTranslation();
  const [picked, setPicked] = useState<DemoUpload[]>([]);
  const active = picked.some((item) => item.progress < 1);

  useEffect(() => {
    if (!active) return;
    const timer = setInterval(() => {
      setPicked((current) =>
        current.map((item) => ({ ...item, progress: Math.min(1, item.progress + DEMO_STEP) })),
      );
    }, DEMO_TICK_MS);
    return () => clearInterval(timer);
  }, [active]);

  const add = (files: File[]) =>
    setPicked((current) => [
      ...current,
      ...files.map((file, i) => ({ key: current.length + i, file, progress: 0 })),
    ]);
  const failed = {
    state: 'failed' as const,
    retryLabel: t('action.retry'),
    onRemove: () => {},
    removeLabel: t('photo.remove'),
  };

  return (
    <Stack gap={12}>
      <div className="grid grid-cols-3 gap-2">
        <AddTile
          label={t('photo.addMedia')}
          accept="image/*,video/mp4,video/quicktime"
          multiple
          onFiles={add}
          className="h-28"
        />
        {picked.map((item) =>
          item.progress < 1 ? (
            <UploadTile
              key={item.key}
              state="uploading"
              progress={item.progress}
              label={t('photo.uploading', { percent: Math.round(item.progress * 100) })}
              className="h-28"
            />
          ) : (
            <Photo
              key={item.key}
              file={item.file}
              alt={t('photo.work')}
              video={item.file.type.startsWith('video/')}
              className="h-28 w-full"
            />
          ),
        )}
        <UploadTile
          state="uploading"
          progress={0.64}
          label={t('photo.uploading', { percent: 64 })}
          className="h-28"
        />
        <UploadTile
          {...failed}
          label={t('photo.uploadFailed')}
          onRetry={() => {}}
          className="h-28"
        />
      </div>
      <HStack gap={8}>
        <Photo alt={t('photo.work')} className="size-18" />
        <UploadTile
          state="uploading"
          compact
          progress={0.3}
          label={t('photo.uploading', { percent: 30 })}
          className="size-18"
        />
        {/* отклонённый файл: повторять нечего */}
        <UploadTile {...failed} label={t('photo.rejected')} compact className="size-18" />
        <AddTile
          icon="camera"
          label={t('photo.add')}
          accept="image/*"
          multiple
          onFiles={add}
          className="size-18"
        />
      </HStack>
    </Stack>
  );
}
