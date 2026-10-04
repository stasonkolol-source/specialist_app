// S49b «Аккаунт ограничен» (DEVELOPMENT_PLAN 1.5a, 2.5b): вид санкции, срок и причина — из ответа
// 403 `restricted`. «Обжаловать» — MainButton макета: `POST /appeals` с видом санкции, сервер
// находит её решение; после — «Апелляция отправлена» со сроком ответа (72 ч) или «уже
// обжаловано» с итогом, кнопка уходит. Правила площадки открываются здесь же (S48): экран
// работает и поверх всего приложения, где роутера нет. «Как принято решение» макета — нет:
// в ответе 403 этого признака нет (модератор или автопроверка), а гадать не будем.
import type { AppealOut } from '@sosed/api-client';
import { ApiError } from '@sosed/api-client';
import { color } from '@sosed/design-tokens';
import type { LegalDocumentKey } from '@sosed/hooks';
import { useAppeal } from '@sosed/hooks';
import { useFormat, useTranslation } from '@sosed/i18n';
import { useBackButton, useColorScheme, useMainButton } from '@sosed/platform';
import { Banner, Card, Group, Heading, Icon, Row, SectionTitle, Text } from '@sosed/ui-web';
import { useId, useState } from 'react';

import { LegalView } from '../s48-legal/LegalView.tsx';
import type { RestrictedState } from './store.ts';

export interface RestrictedScreenProps {
  state: RestrictedState;
  /** «Назад» Telegram — когда экран открыт поверх другого (частичная санкция действия). */
  onBack?: () => void;
}

export function RestrictedScreen({ state, onBack }: RestrictedScreenProps) {
  const [rules, setRules] = useState<LegalDocumentKey | null>(null);
  useBackButton(onBack ?? null);
  // правила поверх S49b: их «Назад» срабатывает первым
  useBackButton(rules ? () => setRules(null) : null);
  if (rules) return <LegalView document={rules} onDocumentChange={setRules} />;
  return <Restriction state={state} onRules={() => setRules('terms')} />;
}

function Restriction({ state, onRules }: { state: RestrictedState; onRules: () => void }) {
  const { t } = useTranslation('service');
  const format = useFormat();
  const leftId = useId();
  const appeal = useAppealButton(state);
  const kind = state.restriction ?? 'other';
  const action = t('restricted.action', { kind });
  const until = state.until;
  const title = until
    ? t('restricted.titleUntil', { kind, date: format.date(until) })
    : t('restricted.title', { kind });
  const banner = until
    ? t('restricted.bannerUntil', { date: format.date(until), time: format.time(until), action })
    : t('restricted.banner', { action });

  return (
    <section className="flex flex-col gap-4 px-4 pt-4 pb-6">
      <div className="flex flex-col items-start gap-3">
        <span className="flex size-16 items-center justify-center rounded-full bg-danger-soft text-danger">
          <Icon name="lock" size={32} />
        </span>
        {/* «до 3 октября» не разрывается между строками: заголовок выравнивается по строкам */}
        <Heading variant="h2" className="text-balance">
          {title}
        </Heading>
      </div>
      <Banner tone="danger" icon="ban" role="alert">
        {banner}
      </Banner>
      {state.reason && (
        <section
          aria-label={t('restricted.decision')}
          className="flex flex-col gap-1 overflow-hidden rounded-card bg-surface px-4 py-3"
        >
          <Text variant="cap" secondary>
            {t('restricted.reasonLabel')}
          </Text>
          <Text>{t('restricted.reason', { code: state.reason })}</Text>
        </section>
      )}
      {/* Санкция на весь аккаунт закрывает и переписку, и настройки: списка «доступно» нет */}
      {!state.blocking && (
        <section className="flex flex-col gap-2" aria-labelledby={leftId}>
          <SectionTitle>
            <span id={leftId}>{t('restricted.left')}</span>
          </SectionTitle>
          <Card as="ul" tight>
            {(['leftDeals', 'leftBrowse', 'leftSettings'] as const).map((key) => (
              <li key={key} className="flex items-center gap-2">
                <Icon name="check-circle" className="text-accent" />
                {t(`restricted.${key}`)}
              </li>
            ))}
          </Card>
        </section>
      )}
      {appeal.filed ? (
        <AppealFiled filed={appeal.filed} />
      ) : (
        <Text variant="cap" className="px-1">
          {t('restricted.appeal')}
        </Text>
      )}
      {appeal.failed && (
        <Banner tone="danger" role="alert">
          {appeal.detail ?? t('restricted.appealError')}
        </Banner>
      )}
      <Group>
        <Row icon="file" title={t('legal.title.terms')} chevron onClick={onRules} />
      </Group>
    </section>
  );
}

/** MainButton «Обжаловать»: пока апелляции нет; ответ сервера — состояние под баннером. */
function useAppealButton(state: RestrictedState) {
  const { t } = useTranslation('service');
  const palette = color[useColorScheme()];
  const appeal = useAppeal();
  const filed = appeal.data ?? null;
  useMainButton({
    text: t('restricted.appealButton'),
    visible: filed === null,
    enabled: !appeal.isPending,
    loading: appeal.isPending,
    color: palette.accent,
    textColor: palette['accent-ink'],
    onClick: () => appeal.mutate(state.restriction ? { restriction: state.restriction } : {}),
  });
  return { filed, failed: appeal.isError, detail: problemDetail(appeal.error) };
}

/** «Апелляция отправлена» со сроком ответа или «уже обжаловано» с итогом. */
function AppealFiled({ filed }: { filed: AppealOut }) {
  const { t } = useTranslation('service');
  const format = useFormat();
  const due = new Date(filed.due_at);
  const when = { date: format.date(due), time: format.time(due) };
  return (
    <Banner tone="ok" role="status">
      {filed.repeated
        ? t('restricted.appealRepeated', { status: filed.status, ...when })
        : t('restricted.appealSent', when)}
    </Banner>
  );
}

/** Нечего обжаловать или срок прошёл — текст сервера; остальное — общий текст экрана. */
function problemDetail(error: unknown): string | null {
  if (error instanceof ApiError && (error.status === 404 || error.status === 409)) {
    return error.problem.detail ?? null;
  }
  return null;
}
