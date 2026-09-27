// Разделы галереи: каждый компонент во всех вариантах. Тексты — из каталогов i18n, имена — данные.
import type { Locale } from '@sosed/i18n';
import { LOCALES, LOCALE_NAMES, useFormat, useTranslation } from '@sosed/i18n';
import type { ReactNode } from 'react';

import { MoreSections } from './GalleryMore.tsx';
import {
  Avatar,
  Badge,
  Button,
  Card,
  HStack,
  Heading,
  ICON_NAMES,
  Icon,
  IconButton,
  SectionTitle,
  Stack,
  TabBar,
  Text,
} from '../src/index.ts';

const SPECIALISTS = [
  { name: 'Алексей Морозов', palette: 1 },
  { name: 'Дмитрий Соколов', palette: 2 },
  { name: 'Никола Петрович', palette: 3 },
  { name: 'Мария Ковалёва', palette: 4 },
  { name: 'Ольга Власова', palette: 5 },
] as const;

const SIZES = ['xs', 'sm', 'md', 'lg', 'xl'] as const;
const THEMES = ['light', 'dark'] as const;

function Section({ id, name, children }: { id: string; name: string; children: ReactNode }) {
  return (
    <section
      data-gallery={id}
      aria-labelledby={`g-${id}`}
      className="flex flex-col gap-3 bg-bg2 py-4"
    >
      <SectionTitle>
        <span id={`g-${id}`}>{name}</span>
      </SectionTitle>
      <div className="px-4">{children}</div>
    </section>
  );
}

export function Gallery({ theme, locale }: { theme: string; locale: Locale }) {
  const { t } = useTranslation();
  const format = useFormat();
  const tabs = [
    { id: 'home', label: t('nav.home'), icon: 'home', href: '#home' },
    { id: 'jobs', label: t('nav.jobs'), icon: 'jobs', href: '#jobs', count: 3 },
    { id: 'chats', label: t('nav.messages'), icon: 'chat', href: '#chats', count: 2 },
    { id: 'me', label: t('nav.profile'), icon: 'user', href: '#me' },
  ] as const;

  return (
    <main className="mx-auto flex max-w-97.5 flex-col bg-bg2 text-text">
      <nav data-gallery-controls className="flex flex-wrap gap-2 p-4 text-cap">
        {THEMES.map((th) => (
          <a
            key={th}
            href={`?theme=${th}&lang=${locale}`}
            aria-current={th === theme ? 'true' : undefined}
          >
            {th}
          </a>
        ))}
        {LOCALES.map((l) => (
          <a
            key={l}
            href={`?theme=${theme}&lang=${l}`}
            aria-current={l === locale ? 'true' : undefined}
          >
            {LOCALE_NAMES[l]}
          </a>
        ))}
      </nav>

      <Section id="typography" name="Heading · SectionTitle · Text">
        <Stack gap={8}>
          <Heading variant="h1-xl">{t('app.name')}</Heading>
          <Heading variant="h1">{t('app.tagline')}</Heading>
          <Heading variant="h2">{t('status.deal.agreed')}</Heading>
          <Heading variant="h3" as="h3">
            {t('rating.new')}
          </Heading>
          <Text>{t('count.respondWithSlots', { count: 2 })}</Text>
          <Text variant="sm">{format.price({ type: 'from', min: 200_000, unit: 'visit' })}</Text>
          <Text variant="cap">{`${format.distance(1_500)} · ${t('count.reviews', { count: 37 })}`}</Text>
        </Stack>
      </Section>

      <Section id="buttons" name="Button · IconButton">
        <Stack gap={12}>
          <Button full>{t('action.respond')}</Button>
          <HStack wrap>
            <Button variant="secondary" icon="chat">
              {t('action.write')}
            </Button>
            <Button variant="outline" icon="share">
              {t('action.share')}
            </Button>
          </HStack>
          <HStack wrap>
            <Button variant="danger">{t('action.cancel')}</Button>
            <Button disabled>{t('action.publish')}</Button>
          </HStack>
          <HStack wrap>
            <Button variant="secondary" size="sm">
              {t('action.confirm')}
            </Button>
            <Button variant="outline" size="sm">
              {t('action.decline')}
            </Button>
          </HStack>
          <HStack>
            <IconButton icon="heart" label={t('action.save')} active />
            <IconButton icon="share" label={t('action.share')} />
            <IconButton icon="more" label={t('action.report')} plain />
          </HStack>
        </Stack>
      </Section>

      <Section id="badges" name="Badge">
        <HStack wrap>
          <Badge tone="ok" icon="check">
            {t('count.firstResponder')}
          </Badge>
          <Badge tone="urgent" icon="zap">
            {t('urgency.asap')}
          </Badge>
          <Badge tone="info">{t('status.job.pending_moderation')}</Badge>
          <Badge tone="mute">{t('glossary.gig')}</Badge>
          <Badge tone="pro">{t('status.deal.agreed')}</Badge>
          <Badge tone="danger">{t('status.deal.disputed')}</Badge>
        </HStack>
      </Section>

      <Section id="avatars" name="Avatar">
        <Stack gap={12}>
          <HStack>
            {SPECIALISTS.map((s) => (
              <Avatar key={s.name} name={s.name} palette={s.palette} />
            ))}
          </HStack>
          <HStack>
            {SIZES.map((size) => (
              <Avatar key={size} name={SPECIALISTS[0].name} palette={1} size={size} />
            ))}
          </HStack>
        </Stack>
      </Section>

      <Section id="cards" name="Card · Stack · HStack">
        <Stack gap={12}>
          <Card>
            <HStack between>
              <Heading variant="h3" as="h3">
                {t('glossary.job')}
              </Heading>
              <Badge tone="urgent">{t('urgency.today')}</Badge>
            </HStack>
            <Text variant="cap">{`${format.distance(1_200)} · ${t('count.responsesOf', { count: 3, total: 5 })}`}</Text>
            <Text variant="title">{format.money(500_000)}</Text>
          </Card>
          <Card tight href="#card">
            <HStack gap={12}>
              <Avatar name={SPECIALISTS[0].name} palette={1} />
              <Stack gap={4}>
                <Text variant="title">{SPECIALISTS[0].name}</Text>
                <Text variant="cap">{t('count.reviews', { count: 37 })}</Text>
              </Stack>
            </HStack>
          </Card>
        </Stack>
      </Section>

      <MoreSections />

      <Section id="icons" name="Icon">
        <div className="grid grid-cols-6 gap-3 text-text">
          {ICON_NAMES.map((name) => (
            <span key={name} title={name} className="flex items-center justify-center">
              <Icon name={name} size={24} className={name === 'star' ? 'text-star' : undefined} />
            </span>
          ))}
        </div>
      </Section>

      <Section id="tabbar" name="TabBar">
        <TabBar
          items={[...tabs]}
          activeId="home"
          plus={{ label: t('nav.create'), href: '#create' }}
          label={t('nav.sections')}
          position="static"
        />
      </Section>
    </main>
  );
}
