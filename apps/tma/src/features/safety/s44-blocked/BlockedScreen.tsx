// S44 Заблокированные (DEVELOPMENT_PLAN 4.7): кого я заблокировал — «Олег Р.» и с какого дня, у
// специалиста — его фото; «Разблокировать» убирает строку сразу (ошибка возвращает её), выдача,
// ленты и переписка перечитываются в фоне. Памятка: угрожает или просит предоплату — не только
// заблокировать, но и пожаловаться; и где жалуются и блокируют — внизу профиля S08 и в меню «⋯»
// чата S30. Пустой список: вступление «Они не могут…» не к кому отнести, а пустое состояние
// говорит то же — вступления нет. Сербская дата после «Od» — в родительном падеже.
// Вход — строка «Заблокированные» на S43; список тот же, что у меню S08 и S30 (GET /me/blocks).
import type { BlockedUserOut, CardPhotoOut } from '@sosed/api-client';
import { useBlocks, useToggleBlock } from '@sosed/hooks';
import { useFormat, useTranslation } from '@sosed/i18n';
import { useBackButton } from '@sosed/platform';
import {
  Avatar,
  Banner,
  Button,
  Card,
  EmptyState,
  Group,
  Heading,
  RowsSkeleton,
  Text,
  paletteFor,
} from '@sosed/ui-web';
import { useRouter } from '@tanstack/react-router';
import { useId } from 'react';

/** Настройки S43: сюда — «Назад» без истории. Фичи друг друга не импортируют — адрес строкой. */
const SETTINGS_PATH = '/settings';
/** Аватар sm — 36 px: фото берём не меньше втрое больше (плотные экраны). */
const AVATAR_SM = 36;

export function BlockedScreen() {
  const { t } = useTranslation('safety');
  const router = useRouter();
  const blocks = useBlocks();
  const toggle = useToggleBlock();
  const howId = useId();
  useBackButton(() => {
    if (router.history.canGoBack()) router.history.back();
    else void router.navigate({ to: SETTINGS_PATH, replace: true });
  });

  const items = blocks.data?.items;
  return (
    <section className="flex flex-col gap-3.5 px-4 pt-3 pb-6">
      <div className="flex flex-col gap-2">
        <Heading variant="h2" as="h1">
          {t('blocked.title')}
        </Heading>
        {items?.length !== 0 && (
          <Text variant="sm" secondary>
            {t('blocked.intro')}
          </Text>
        )}
      </div>
      {items === undefined ? (
        <div role="status">
          <span className="sr-only">{t('blocked.loading')}</span>
          <RowsSkeleton rows={2} trailing />
        </div>
      ) : items.length === 0 ? (
        <EmptyState icon="ban" tone="neutral" as="h2" title={t('blocked.emptyTitle')}>
          {t('blocked.emptyText')}
        </EmptyState>
      ) : (
        <Group>
          <ul aria-label={t('blocked.listLabel')} className="m-0 list-none p-0">
            {items.map((user) => (
              <BlockedRow
                key={user.user_id}
                user={user}
                busy={toggle.isPending && toggle.variables.user.user_id === user.user_id}
                onUnblock={() => toggle.mutate({ user, on: false })}
              />
            ))}
          </ul>
        </Group>
      )}
      {toggle.isError && (
        <Banner tone="danger" role="alert">
          {t('blocked.unblockError')}
        </Banner>
      )}
      <Banner tone="warn">{t('blocked.warning')}</Banner>
      <Card as="section" tight aria-labelledby={howId}>
        <Heading variant="h3" as="h2" id={howId}>
          {t('blocked.howTitle')}
        </Heading>
        <Text variant="sm" secondary>
          {t('blocked.howText')}
        </Text>
      </Card>
    </section>
  );
}

function BlockedRow({
  user,
  busy,
  onUnblock,
}: {
  user: BlockedUserOut;
  busy: boolean;
  onUnblock: () => void;
}) {
  const { t } = useTranslation('safety');
  const { t: common } = useTranslation();
  const format = useFormat();
  return (
    <li className="flex min-h-13 items-center gap-3 border-0 border-b border-solid border-line px-4 py-3 last:border-b-0">
      <Avatar
        name={user.display_name}
        size="sm"
        palette={paletteFor(user.user_id)}
        src={photoSrc(user.avatar)}
        placeholder={user.avatar?.placeholder}
      />
      <span className="flex min-w-0 flex-1 flex-col">
        <span className="truncate text-body font-semibold">{user.display_name}</span>
        <span className="text-cap text-text2">
          {t('blocked.since', { date: format.dateGenitive(new Date(user.blocked_at)) })}
        </span>
      </span>
      <Button
        size="sm"
        variant="outline"
        disabled={busy}
        aria-busy={busy}
        aria-label={t('blocked.unblockLabel', { name: user.display_name })}
        onClick={onUnblock}
      >
        {common('action.unblock')}
      </Button>
    </li>
  );
}

/** Миниатюра фото профиля: вариант не меньше втрое больше аватара. */
function photoSrc(photo: CardPhotoOut | null): string | undefined {
  if (!photo) return undefined;
  const sorted = [...photo.variants].sort((a, b) => a.width - b.width);
  return (sorted.find((variant) => variant.width >= AVATAR_SM * 3) ?? sorted.at(-1))?.url;
}
