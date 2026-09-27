// Разделы галереи для компонентов 0.19b.
import { useFormat, useTranslation } from '@sosed/i18n';
import type { ReactNode } from 'react';
import { useState } from 'react';

import {
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
  Option,
  Photo,
  Price,
  ProgressBar,
  Row,
  SearchField,
  Segmented,
  Skeleton,
  Stack,
  Stars,
  Steps,
  Switch,
  Textarea,
  Tile,
  Tiles,
  Toast,
} from '../src/index.ts';

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
  const format = useFormat();
  const [urgency, setUrgency] = useState<'asap' | 'today' | 'this_week'>('today');
  const [budget, setBudget] = useState<'fixed' | 'range'>('fixed');
  const [langs, setLangs] = useState(true);
  const [notify, setNotify] = useState(true);
  const [stars, setStars] = useState(4);

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

      <Section id="form" name="SearchField · Field · Input · Textarea">
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
        </Stack>
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
    </>
  );
}
