// Город S43 (DEVELOPMENT_PLAN 4.9): строка с текущим городом открывает шторку с городами, как
// выбор на S02a: пилотный выбирается, остальные — «скоро». Выбор сохраняет PATCH /me, ответ
// ложится в кэш /me — Главная и выдача берут город оттуда.
import type { CityOut, MeOut } from '@sosed/api-client';
import { getIdentityGetMeQueryKey, useIdentityUpdateMe } from '@sosed/api-client';
import { isSelectableCity, useCities } from '@sosed/hooks';
import { useLocale, useTranslation } from '@sosed/i18n';
import { useBackButton, usePlatform } from '@sosed/platform';
import {
  Badge,
  Banner,
  Group,
  Option,
  RadioGroup,
  Row,
  Sheet,
  SkeletonText,
  Text,
} from '@sosed/ui-web';
import { useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

export function City({ me }: { me: MeOut }) {
  const { t } = useTranslation('account');
  const { t: common } = useTranslation();
  const platform = usePlatform();
  const queryClient = useQueryClient();
  const cities = useCities(useLocale());
  const [open, setOpen] = useState(false);
  const close = () => setOpen(false);
  // «Назад» Telegram закрывает шторку, а не уходит с экрана
  useBackButton(open ? close : null);
  const update = useIdentityUpdateMe({
    mutation: {
      onSuccess: (next) => {
        queryClient.setQueryData(getIdentityGetMeQueryKey(), next);
        setOpen(false);
      },
    },
  });
  const current = update.isPending ? update.variables.data.home_city_id : me.home_city_id;
  const city = cities.data?.find((candidate) => candidate.id === me.home_city_id);

  const choose = (id: number) => {
    if (update.isPending) return;
    if (id === me.home_city_id) {
      close();
      return;
    }
    platform.haptics.selection();
    update.mutate({ data: { home_city_id: id } });
  };

  return (
    <>
      <Group>
        <Row
          icon="pin"
          title={t('settings.city')}
          trailing={
            city ? (
              <Text as="span" secondary>
                {city.name}
              </Text>
            ) : (
              cities.isPending && <SkeletonText className="w-20" />
            )
          }
          chevron
          onClick={() => {
            update.reset();
            setOpen(true);
          }}
        />
      </Group>
      <Sheet
        open={open}
        title={t('settings.cityTitle')}
        onClose={close}
        closeLabel={common('action.close')}
      >
        <RadioGroup
          label={t('settings.cityTitle')}
          busy={update.isPending}
          className="flex flex-col gap-2"
        >
          {cities.data?.map((option) => (
            <CityOption
              key={option.id}
              city={option}
              checked={option.id === current}
              onChoose={() => choose(option.id)}
            />
          ))}
        </RadioGroup>
        {update.isError && (
          <Banner tone="danger" role="alert">
            {t('settings.saveError')}
          </Banner>
        )}
      </Sheet>
    </>
  );
}

function CityOption({
  city,
  checked,
  onChoose,
}: {
  city: CityOut;
  checked: boolean;
  onChoose: () => void;
}) {
  const { t } = useTranslation('account');
  const selectable = isSelectableCity(city);
  return (
    <Option
      control="start"
      disabled={!selectable}
      title={<span className="font-semibold">{city.name}</span>}
      description={selectable ? t('settings.cityPilot') : undefined}
      trailing={selectable ? undefined : <Badge>{t('settings.soon')}</Badge>}
      checked={checked}
      onChange={onChoose}
    />
  );
}
