// S49b «Аккаунт ограничен» (DEVELOPMENT_PLAN 1.5a): вид санкции и срок — из ответа 403
// `restricted`. Кнопку «Обжаловать» (MainButton макета) и блок «Решение модератора» включает
// шаг 2.5b: до него у клиента нет ни апелляций, ни причины решения. Правила площадки
// открываются здесь же (S48): экран работает и поверх всего приложения, где роутера нет.
import type { LegalDocumentKey } from '@sosed/hooks';
import { useFormat, useTranslation } from '@sosed/i18n';
import { useBackButton } from '@sosed/platform';
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
      <Text variant="cap" className="px-1">
        {t('restricted.appeal')}
      </Text>
      <Group>
        <Row icon="file" title={t('legal.title.terms')} chevron onClick={onRules} />
      </Group>
    </section>
  );
}
