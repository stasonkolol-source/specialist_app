// S04 Категории (DEVELOPMENT_PLAN 4.4): услуги города деревом — раздел раскрывается на месте,
// услуга ведёт в выдачу S05. Справа — сколько специалистов (с подкатегориями), в подписи раздела —
// первые подкатегории перечнем («Электрика, сантехника, сборка мебели и ещё 1»), у услуги —
// ориентир цены города. Строка поиска — тоже в S05. Гость видит экран без входа. Последняя строка,
// как на артборде, — «Не нашли свою услугу?»: мастер заявки S20a (5.2) с набранным в поиске текстом.
import type { CategoryOut } from '@sosed/api-client';
import { useCategories, useCategoryCounts } from '@sosed/hooks';
import { useFormat, useLocale, useTranslation } from '@sosed/i18n';
import { useBackButton } from '@sosed/platform';
import type { AvatarPalette, IconName } from '@sosed/ui-web';
import { Group, Heading, ICON_NAMES, Row, RowIcon, RowsSkeleton, SearchField } from '@sosed/ui-web';
import { useRouter } from '@tanstack/react-router';
import type { FormEvent, MouseEvent } from 'react';
import { Fragment, useState } from 'react';

import { LoadError } from '../shared/LoadError.tsx';
import { useCatalogCity } from '../shared/city.ts';
import type { CreateJobSearch, ResultsSearch } from '../shared/paths.ts';
import { CATALOG_PATHS, CREATE_JOB_PATH } from '../shared/paths.ts';

const HOME_PATH = '/';
const PALETTES = 5;
const PREVIEW_CHILDREN = 3;
const SKELETON_ROWS = 6;

function iconOf(name: string | null): IconName {
  return name !== null && (ICON_NAMES as readonly string[]).includes(name)
    ? (name as IconName)
    : 'grid';
}

/** «Сантехника» внутри перечня — с маленькой буквы; аббревиатуры («IT-помощь») — как есть. */
function lowerFirst(name: string): string {
  return /^\p{Lu}{2}/u.test(name) ? name : name.charAt(0).toLowerCase() + name.slice(1);
}

export function CategoriesScreen() {
  const { t } = useTranslation('catalog');
  const common = useTranslation().t;
  const locale = useLocale();
  const format = useFormat();
  const router = useRouter();
  const city = useCatalogCity();
  const tree = useCategories(locale, city?.slug);
  const counts = useCategoryCounts(city?.id ?? null);
  const [open, setOpen] = useState<number | null>(null);
  const [query, setQuery] = useState('');
  useBackButton(() => {
    if (router.history.canGoBack()) router.history.back();
    else void router.navigate({ to: HOME_PATH, replace: true });
  });

  const results = (search: ResultsSearch) => ({
    href: router.buildLocation({ to: CATALOG_PATHS.results, search }).href,
    onClick: (event: MouseEvent<HTMLElement>) => {
      event.preventDefault();
      void router.navigate({ to: CATALOG_PATHS.results, search });
    },
  });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    const q = query.trim();
    if (q) void router.navigate({ to: CATALOG_PATHS.results, search: { q } });
  };
  // набранное в поиске — готовое название заявки
  const createSearch: CreateJobSearch = query.trim() ? { title: query.trim() } : {};
  const openCreate = (event: MouseEvent<HTMLElement>) => {
    event.preventDefault();
    void router.navigate({ to: CREATE_JOB_PATH, search: createSearch });
  };
  /** Подпись раздела: первые подкатегории перечнем, остальные — «и ещё N». */
  const preview = (children: readonly CategoryOut[]) => {
    const names = children
      .slice(0, PREVIEW_CHILDREN)
      .map((child, index) => (index === 0 ? child.name : lowerFirst(child.name)))
      .join(', ');
    const rest = children.length - PREVIEW_CHILDREN;
    return rest > 0 ? t('categories.more', { names, count: rest }) : names;
  };
  const hint = (node: CategoryOut) =>
    node.price_hint
      ? `${format.moneyRange(node.price_hint.min.amount, node.price_hint.max.amount)} ${common(`unit.${node.price_hint.unit}`)}`
      : undefined;
  const counted = (node: CategoryOut) => {
    const count = counts.data?.get(node.id);
    return count === undefined ? undefined : (
      <span className="text-cap text-text2" aria-label={t('categories.specialists', { count })}>
        {count}
      </span>
    );
  };

  let content;
  if (tree.data) {
    content = (
      <Group>
        {tree.data.map((node, index) => {
          const leading = (
            <RowIcon icon={iconOf(node.icon)} palette={((index % PALETTES) + 1) as AvatarPalette} />
          );
          const title = <span className="font-semibold">{node.name}</span>;
          if (node.children.length === 0) {
            return (
              <Row
                key={node.id}
                leading={leading}
                title={title}
                subtitle={hint(node)}
                trailing={counted(node)}
                chevron
                {...results({ category: node.id })}
              />
            );
          }
          const expanded = open === node.id;
          return (
            <Fragment key={node.id}>
              <Row
                leading={leading}
                title={title}
                subtitle={preview(node.children)}
                trailing={counted(node)}
                expanded={expanded}
                onClick={() => setOpen(expanded ? null : node.id)}
              />
              {expanded &&
                node.children.map((child) => (
                  <Row
                    key={child.id}
                    inset
                    title={child.name}
                    subtitle={hint(child)}
                    trailing={counted(child)}
                    chevron
                    {...results({ category: child.id })}
                  />
                ))}
            </Fragment>
          );
        })}
      </Group>
    );
  } else if (tree.isError) {
    content = (
      <LoadError
        error={tree.error}
        onRetry={() => void tree.refetch()}
        retrying={tree.isRefetching}
      />
    );
  } else {
    // строки дерева в .group: иконка раздела, название с подкатегориями, число справа
    content = (
      <div aria-busy="true">
        <RowsSkeleton rows={SKELETON_ROWS} leading="icon" trailing />
      </div>
    );
  }

  return (
    <section className="flex flex-col gap-3 px-4 pt-3 pb-6">
      <Heading variant="h2" as="h1">
        {t('categories.title')}
      </Heading>
      <form onSubmit={submit}>
        <SearchField
          label={t('categories.search')}
          placeholder={t('categories.search')}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
      </form>
      {content}
      {tree.data && (
        <Group>
          <Row
            icon="plus"
            title={<span className="font-semibold">{t('categories.notFound')}</span>}
            subtitle={t('categories.notFoundText')}
            chevron
            href={router.buildLocation({ to: CREATE_JOB_PATH, search: createSearch }).href}
            onClick={openCreate}
          />
        </Group>
      )}
    </section>
  );
}
