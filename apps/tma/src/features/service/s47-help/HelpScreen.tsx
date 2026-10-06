// S47 Помощь (DEVELOPMENT_PLAN 4.9; PRODUCT, экраны G): правила безопасных сделок, частые вопросы
// с поиском, вход в правила площадки S48. MainButton «Написать в поддержку» — по решению Q25, как
// /help в боте: открывает чат с аккаунтом поддержки из client-config; пока владелец его не дал
// (K23) — неактивная кнопка «Поддержка — скоро». Вход — строка «Помощь» на S31. Тексты — в
// неймспейсе account (экраны из профиля), экран — своим чанком.
import { color } from '@sosed/design-tokens';
import { useSupportLink } from '@sosed/hooks';
import { useTranslation } from '@sosed/i18n';
import { useBackButton, useColorScheme, useMainButton, usePlatform } from '@sosed/platform';
import { Card, Group, Heading, Icon, Row, RowIcon, SearchField, SectionTitle } from '@sosed/ui-web';
import { useRouter } from '@tanstack/react-router';
import type { MouseEvent } from 'react';
import { useId, useState } from 'react';

/** Профиль S31 — куда «Назад» без истории (маршрут фичи account). */
const FALLBACK_PATH = '/profile';
/** S48, правила площадки (маршрут features/service/s48-legal). */
const LEGAL_PATH = '/legal/$document';
const RULES_HREF = '/legal/terms';

const SAFETY = ['prepay', 'links'] as const;
const FAQ = ['responses', 'contacts', 'review', 'price'] as const;
type Question = (typeof FAQ)[number];

export function HelpScreen() {
  const { t } = useTranslation('account');
  const router = useRouter();
  useBackButton(() => {
    if (router.history.canGoBack()) router.history.back();
    else void router.navigate({ to: FALLBACK_PATH, replace: true });
  });
  useSupportButton();
  const openRules = (event: MouseEvent<HTMLElement>) => {
    event.preventDefault();
    void router.navigate({ to: LEGAL_PATH, params: { document: 'terms' } });
  };

  return (
    <section className="flex flex-col gap-4 px-4 pt-3 pb-6">
      <Heading variant="h2" as="h1">
        {t('help.title')}
      </Heading>
      <Faq />
      <Group>
        <Row
          icon="file"
          title={t('help.rules')}
          subtitle={t('help.rulesHint')}
          chevron
          href={router.history.createHref(RULES_HREF)}
          onClick={openRules}
        />
      </Group>
    </section>
  );
}

/** «Написать в поддержку»: чат с поддержкой в Telegram; без контакта — серая кнопка «скоро». */
function useSupportButton() {
  const { t } = useTranslation('account');
  const platform = usePlatform();
  const palette = color[useColorScheme()];
  const support = useSupportLink();
  useMainButton({
    text: support ? t('help.support') : t('help.supportSoon'),
    enabled: support !== null,
    color: support ? palette.accent : palette.bg2,
    textColor: support ? palette['accent-ink'] : palette.text2,
    onClick: () => {
      if (support) platform.openTelegramLink(support);
    },
  });
}

/** Поиск, безопасность и вопросы: поиск оставляет вопросы, где есть все слова запроса, и
 *  раскрывает их. Без поиска раскрыт первый вопрос, как на артборде. Ничего не нашлось — зовём в
 *  поддержку, только если она есть: без контакта MainButton — серая «Поддержка — скоро». */
function Faq() {
  const { t } = useTranslation('account');
  const support = useSupportLink();
  const titleId = useId();
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState<ReadonlySet<Question>>(() => new Set(['responses']));
  const words = query.toLocaleLowerCase().split(/\s+/).filter(Boolean);
  const found = FAQ.filter((key) => {
    const text = `${t(`help.faq.${key}.q`)} ${t(`help.faq.${key}.a`)}`.toLocaleLowerCase();
    return words.every((word) => text.includes(word));
  });
  const toggle = (key: Question) =>
    setOpen((current) => {
      const next = new Set(current);
      if (!next.delete(key)) next.add(key);
      return next;
    });

  return (
    <>
      <SearchField
        label={t('help.search')}
        placeholder={t('help.search')}
        value={query}
        onChange={(event) => setQuery(event.target.value)}
      />
      <Safety />
      <section aria-labelledby={titleId} className="flex flex-col gap-2">
        <SectionTitle id={titleId}>{t('help.faqTitle')}</SectionTitle>
        {found.length > 0 ? (
          <Group>
            {found.map((key) => (
              <Answer
                key={key}
                question={t(`help.faq.${key}.q`)}
                answer={t(`help.faq.${key}.a`)}
                // при поиске найденное раскрыто: ответ — то, что ищут
                expanded={words.length > 0 || open.has(key)}
                onToggle={() => toggle(key)}
              />
            ))}
          </Group>
        ) : (
          <p role="status" className="m-0 px-4 text-sm text-text2">
            {support ? t('help.nothingFound') : t('help.nothingFoundNoSupport')}
          </p>
        )}
      </section>
    </>
  );
}

function Safety() {
  const { t } = useTranslation('account');
  const titleId = useId();
  return (
    <Card as="section" tight aria-labelledby={titleId}>
      <span className="flex items-center gap-2.5">
        <RowIcon icon="shield" />
        <Heading variant="h3" as="h2" id={titleId}>
          {t('help.safetyTitle')}
        </Heading>
      </span>
      <ul className="m-0 flex list-none flex-col gap-2 p-0">
        {SAFETY.map((key) => (
          <li key={key} className="flex items-center gap-2.5 text-sm">
            <Icon name="ban" className="shrink-0 text-danger" />
            {t(`help.safety.${key}`)}
          </li>
        ))}
      </ul>
    </Card>
  );
}

/** Вопрос-раскрывашка: кнопка с aria-expanded, ответ под ней. */
function Answer({
  question,
  answer,
  expanded,
  onToggle,
}: {
  question: string;
  answer: string;
  expanded: boolean;
  onToggle: () => void;
}) {
  const answerId = useId();
  return (
    <div className="border-b border-line last:border-b-0">
      <button
        type="button"
        aria-expanded={expanded}
        aria-controls={answerId}
        onClick={onToggle}
        className="flex min-h-13 w-full items-center justify-between gap-3 border-0 bg-transparent px-4 py-3 text-left text-body text-text outline-none focus-visible:outline-2 focus-visible:outline-solid focus-visible:-outline-offset-2 focus-visible:outline-accent"
      >
        <span className={expanded ? 'font-semibold' : undefined}>{question}</span>
        <Icon
          name="chev-down"
          className={expanded ? 'shrink-0 rotate-180 text-text2' : 'shrink-0 text-text2'}
        />
      </button>
      {/* между вопросом и ответом — 8 px, как на артборде: отступ кнопки снизу 12 */}
      <p id={answerId} hidden={!expanded} className="m-0 -mt-1 px-4 pb-3 text-sm text-text2">
        {answer}
      </p>
    </div>
  );
}
