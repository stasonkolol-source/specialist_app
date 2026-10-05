// S48 Правовые документы (DEVELOPMENT_PLAN 1.5a): правила площадки и политика конфиденциальности
// действующей версии из client-config. Шапка — заголовок, «Редакция от <даты>» и переключатель
// документов; текст — пронумерованные разделы, как пункты правил на макете. Номер версии остаётся
// в данных (согласия, client-config) — человеку он ничего не говорит. Текст документа — основным
// размером (SPEC §5: 15/22), вступление — 14/20, заголовки разделов — 16/22: правила читают, а не
// пробегают как сноску. Markdown разбирается в элементы React: HTML из текста не исполняется.
import type { LegalDocumentKey } from '@sosed/hooks';
import { LEGAL_DOCUMENTS, systemStateOf, useLegalDocument } from '@sosed/hooks';
import { useFormat, useLocale, useTranslation } from '@sosed/i18n';
import {
  Banner,
  Button,
  Card,
  EmptyState,
  Heading,
  Icon,
  MarkdownBlocks,
  NumIcon,
  Segmented,
  Skeleton,
  Text,
} from '@sosed/ui-web';
import type { MarkdownInline } from '@sosed/ui-web';
import type { ReactNode } from 'react';
import { useMemo } from 'react';

import { outline } from './sections.ts';

export interface LegalViewProps {
  document: LegalDocumentKey;
  onDocumentChange: (document: LegalDocumentKey) => void;
}

export function LegalView({ document, onDocumentChange }: LegalViewProps) {
  const { t } = useTranslation('service');
  const format = useFormat();
  const locale = useLocale();
  const legal = useLegalDocument(document, locale);
  const edition = legal.document;

  return (
    <section className="flex flex-col gap-4 px-4 pt-3 pb-6">
      <div className="flex flex-col gap-1">
        <Heading variant="h2">{t(`legal.title.${document}`)}</Heading>
        {edition && (
          <Text variant="cap">
            {t('legal.edition', { date: format.fullDateGenitive(new Date(edition.published_on)) })}
          </Text>
        )}
      </div>
      <Segmented<LegalDocumentKey>
        label={t('legal.segment')}
        value={document}
        onChange={onDocumentChange}
        options={LEGAL_DOCUMENTS.map((key) => ({ value: key, label: t(`legal.tab.${key}`) }))}
      />
      <LegalBody legal={legal} />
    </section>
  );
}

function LegalBody({ legal }: { legal: ReturnType<typeof useLegalDocument> }) {
  const { t } = useTranslation('service');
  const { config, text, translated } = legal;
  if (config.isPending) return <Loading />;
  if (!text) {
    return config.isError ? (
      <LoadError
        error={config.error}
        onRetry={() => void config.refetch()}
        retrying={config.isFetching}
      />
    ) : (
      <EmptyState as="h2" icon="file" title={t('legal.unavailableTitle')}>
        {t('legal.unavailableText')}
      </EmptyState>
    );
  }
  return (
    <>
      {!translated && (
        <Banner tone="info" icon="languages">
          {t('legal.untranslated')}
        </Banner>
      )}
      <Sections body={text.body} lang={translated ? undefined : text.locale} />
    </>
  );
}

function Sections({ body, lang }: { body: string; lang: string | undefined }) {
  const { intro, sections } = useMemo(() => outline(body), [body]);
  return (
    <Card className="gap-3.5">
      {intro.length > 0 && (
        <MarkdownBlocks blocks={intro} className="text-sm text-text2" lang={lang} />
      )}
      <ol lang={lang} className="m-0 flex list-none flex-col gap-3.5 p-0">
        {sections.map((section, i) => (
          <li key={i} className="flex items-start gap-3">
            <NumIcon>{section.number ?? <Icon name="info" size={16} />}</NumIcon>
            <div className="flex min-w-0 flex-1 flex-col gap-1">
              <h2 className="m-0 text-title">{inline(section.title)}</h2>
              {/* абзацы — через 8 px, пункты списка — через 4 px (MarkdownBlocks) */}
              {section.blocks.length > 0 && (
                <MarkdownBlocks
                  blocks={section.blocks}
                  headingLevel={3}
                  className="text-body text-text"
                />
              )}
            </div>
          </li>
        ))}
      </ol>
    </Card>
  );
}

/** Заголовок раздела: только текст и выделение, без ссылок — он и так жирный. */
function inline(nodes: MarkdownInline[]): ReactNode {
  return nodes.map((node) =>
    node.type === 'text' || node.type === 'code' ? node.value : inline(node.children),
  );
}

function Loading() {
  const { t } = useTranslation('service');
  return (
    <Card className="gap-3.5">
      <div role="status">
        <span className="sr-only">{t('legal.loading')}</span>
      </div>
      {[0, 1, 2, 3].map((i) => (
        <div key={i} className="flex items-start gap-3">
          <Skeleton round className="size-7" />
          <div className="flex flex-1 flex-col gap-1.5">
            <Skeleton className="h-4 w-2/3" />
            <Skeleton className="h-3 w-full" />
            <Skeleton className="h-3 w-4/5" />
          </div>
        </div>
      ))}
    </Card>
  );
}

function LoadError({
  error,
  onRetry,
  retrying,
}: {
  error: unknown;
  onRetry: () => void;
  retrying: boolean;
}) {
  const { t } = useTranslation();
  const offline = systemStateOf(error).kind === 'offline';
  return (
    <EmptyState
      as="h2"
      size="h2"
      tone={offline ? 'neutral' : 'accent'}
      icon={offline ? 'wifi-off' : 'alert'}
      title={offline ? t('offline.title') : t('error.title')}
      className="px-6 pt-2"
      action={
        <Button
          variant="secondary"
          icon="refresh"
          onClick={onRetry}
          disabled={retrying}
          aria-busy={retrying}
        >
          {t('action.retry')}
        </Button>
      }
    >
      {offline ? t('offline.textEmpty') : t('error.text')}
    </EmptyState>
  );
}
