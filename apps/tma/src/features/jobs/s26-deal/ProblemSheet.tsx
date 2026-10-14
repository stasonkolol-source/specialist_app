// «Есть проблема» S26 — три пути вместо спора на любую беду (решение 2026-10-14; тот же выбор — в
// боте под «Работа выполнена?»). Клиенту: «Не пришёл или нет связи» — отменить сделку (`no_contact`:
// заявка снова открыта, на исполнителя — тихая жалоба `no_show`), «Просит предоплату» — жалоба в
// один тап, «Сделал плохо или ущерб» — спор S52. Исполнителю: «Клиент не выходит на связь» —
// отменить, «Другая проблема» — спор. Работу уже отметили — отменить нельзя (MU-8): «не пришёл»
// ведёт в спор. Шторка — своим чанком при первом открытии (DealScreen, React.lazy).
import { useTranslation } from '@sosed/i18n';
import { useBackButton } from '@sosed/platform';
import type { IconName } from '@sosed/ui-web';
import { Group, Row, Sheet } from '@sosed/ui-web';

export interface ProblemSheetProps {
  client: boolean;
  /** Работу отметили «выполнено» — сделку не отменить, «не пришёл» — спор. */
  marked: boolean;
  /** Сделка по отклику: после отмены клиент выбирает другого из откликов. */
  fromResponse: boolean;
  /** Аккаунт второй стороны удалён — жаловаться не на кого. */
  canReport: boolean;
  busy: boolean;
  onNoShow: () => void;
  onReport: () => void;
  onDispute: () => void;
  onClose: () => void;
}

interface Path {
  key: string;
  icon: IconName;
  title: string;
  subtitle: string;
  onClick: () => void;
}

export function ProblemSheet({
  client,
  marked,
  fromResponse,
  canReport,
  busy,
  onNoShow,
  onReport,
  onDispute,
  onClose,
}: ProblemSheetProps) {
  const { t } = useTranslation('jobs');
  const { t: common } = useTranslation();
  useBackButton(onClose);
  const noShow: Path = {
    key: 'no-show',
    icon: 'clock',
    title: t(client ? 'deal.problemSheet.noShow' : 'deal.problemSheet.noShowPerformer'),
    subtitle: marked
      ? t('deal.problemSheet.noShowMarked')
      : client
        ? t(fromResponse ? 'deal.problemSheet.noShowHint' : 'deal.problemSheet.noShowHintChat')
        : t('deal.problemSheet.noShowPerformerHint'),
    onClick: marked ? onDispute : onNoShow,
  };
  const prepayment: Path = {
    key: 'prepayment',
    icon: 'wallet',
    title: t('deal.problemSheet.prepayment'),
    subtitle: t('deal.problemSheet.prepaymentHint'),
    onClick: onReport,
  };
  const paths: Path[] = client
    ? [
        noShow,
        ...(canReport ? [prepayment] : []),
        {
          key: 'quality',
          icon: 'flag',
          title: t('deal.problemSheet.quality'),
          subtitle: t('deal.problemSheet.qualityHint'),
          onClick: onDispute,
        },
      ]
    : [
        noShow,
        {
          key: 'other',
          icon: 'flag',
          title: t('deal.problemSheet.other'),
          subtitle: t('deal.problemSheet.otherHint'),
          onClick: onDispute,
        },
      ];
  return (
    <Sheet
      open
      title={t('deal.problemSheet.title')}
      onClose={onClose}
      closeLabel={common('action.close')}
    >
      <Group>
        {paths.map((path) => (
          <Row
            key={path.key}
            icon={path.icon}
            title={path.title}
            subtitle={path.subtitle}
            chevron
            // пока отмена или жалоба уходят, второе нажатие не уходит (MU-5)
            onClick={() => {
              if (!busy) path.onClick();
            }}
          />
        ))}
      </Group>
    </Sheet>
  );
}
