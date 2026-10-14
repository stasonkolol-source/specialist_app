// Шторка «Что проверено» (сигналы доверия, ZZP 35/2026 ст. 19–20): бейдж «Проверен модератором»
// называет факт, а здесь — что именно проверено и что нет: модератор прочитал описание и
// посмотрел фото профиля и портфолио до публикации (дата — published_at), в профиле нет
// контактов, просьб о предоплате и запрещённых услуг; документы, квалификацию и авторство фото
// не проверяем; отзывы — только по сделкам. «Приглашён командой» — команда лично пригласила
// специалиста из чатов района. Открывается с S08 (бейджи, «Как мы проверяем»), S11 и S24 —
// своим чанком при первом открытии (CheckedHost).
import type { CheckedTarget } from '@sosed/hooks';
import { useFormat, useTranslation } from '@sosed/i18n';
import { useBackButton } from '@sosed/platform';
import { Sheet, Text } from '@sosed/ui-web';

export function CheckedSheet({ target, onClose }: { target: CheckedTarget; onClose: () => void }) {
  const { t } = useTranslation('catalog');
  const { t: common } = useTranslation();
  const format = useFormat();
  useBackButton(onClose);
  if (target.kind === 'founding') {
    return (
      <Sheet
        open
        title={t('checked.foundingTitle')}
        onClose={onClose}
        closeLabel={common('action.close')}
      >
        <Text variant="sm">{t('checked.founding')}</Text>
      </Sheet>
    );
  }
  const checkedAt = target.checkedAt ? new Date(target.checkedAt) : null;
  return (
    <Sheet open title={t('checked.title')} onClose={onClose} closeLabel={common('action.close')}>
      <Text variant="sm">
        {checkedAt
          ? t('checked.read', { date: format.fullDateGenitive(checkedAt) })
          : t('checked.readNoDate')}
      </Text>
      <Text variant="sm">{t('checked.rules')}</Text>
      <Text variant="sm">{t('checked.limits')}</Text>
      <Text variant="sm">{t('checked.reviews')}</Text>
    </Sheet>
  );
}
