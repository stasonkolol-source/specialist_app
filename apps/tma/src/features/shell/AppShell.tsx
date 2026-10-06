// Оболочка экранов: safe area, таббар и нижняя кнопка (DEVELOPMENT_PLAN 0.21a). Тему клиента
// синхронизирует точка сборки (app/App.tsx): экраны S49 при старте рисуются без оболочки.
// Вкладка «Заявки» всегда открывает «Ленту» — все заявки рядом; «Мои отклики» и «Мои заявки» —
// сегментами на ней (решение владельца 2026-10-03; раньше клиенту — сразу «Мои заявки», 5.6).
// Таббар — только на корневых экранах вкладок (SPEC §2) и скрыт, пока показана MainButton: у
// экрана с главным действием нет навигации вниз. Внутренние экраны (S48, S49b) — с «Назад».
// Счётчики вкладок (6.4): «Заявки» — новые отклики на свои заявки, «Сообщения» — непрочитанные.
import { useBadges } from '@sosed/hooks';
import { preloadCatalogs, useTranslation } from '@sosed/i18n';
import { useBottomButtonState, useInsets } from '@sosed/platform';
import type { TabItem } from '@sosed/ui-web';
import { TabBar } from '@sosed/ui-web';
import { useQueryClient } from '@tanstack/react-query';
import { Outlet, useRouter, useRouterState } from '@tanstack/react-router';
import type { MouseEvent } from 'react';
import { useEffect } from 'react';

import { BUTTON_AREA, ContentMainButton } from './ContentButton.tsx';
import { afterFirstScreen, saveData } from './idle.ts';

/** Высота .tabbar из ui.css (h-21): контент не уходит под таббар. */
const TABBAR_HEIGHT = 84;

export const TABS = [
  { id: 'home', path: '/', icon: 'home', label: 'nav.home' },
  { id: 'jobs', path: '/jobs', icon: 'jobs', label: 'nav.jobs' },
  { id: 'messages', path: '/messages', icon: 'chat', label: 'nav.messages' },
  { id: 'profile', path: '/profile', icon: 'user', label: 'nav.profile' },
] as const;

export const CREATE_PATH = '/jobs/new';
const CREATE_ID = 'create';

/** Сегменты вкладки «Заявки» (фича jobs): у каждого свой адрес, таббар виден и на них. */
const JOBS_SEGMENTS = ['/jobs/responses', '/jobs/mine'] as const;
const TAB_ROOTS: ReadonlySet<string> = new Set([...TABS.map((tab) => tab.path), ...JOBS_SEGMENTS]);
/** Куда ведёт вкладка или «+»: путь маршрута, а не href ссылки. У hash history в Telegram
 *  href — «/#/profile»: переход по нему уводил на главную. */
const DESTINATIONS: ReadonlyMap<string, string> = new Map([
  ...TABS.map((tab) => [tab.id, tab.path] as const),
  [CREATE_ID, CREATE_PATH],
]);

const destination = (id: string): string => DESTINATIONS.get(id) ?? '/';

export function AppShell() {
  const { t, i18n } = useTranslation();
  const router = useRouter();
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  const queryClient = useQueryClient();
  const main = useBottomButtonState('main');
  const insets = useInsets();
  // «Заявки N» и «Сообщения N»: новые отклики и непрочитанные (6.4); гостю — без запроса
  const badges = useBadges();

  // Экраны вкладок — отдельные чанки: загрузить их, пока есть сеть, — иначе вкладка, открытая
  // впервые без сети (метро), не откроется совсем. И тексты остальных экранов. Но после того, как
  // первый экран дочитал свои данные: на медленной сети фон не отнимает её у Главной. С Data Saver
  // — не грузим: экран загрузит своё, когда его откроют
  useEffect(() => {
    if (saveData()) return undefined;
    return afterFirstScreen(queryClient, () => {
      for (const id of [...TABS.map((tab) => tab.id), CREATE_ID]) {
        void router.preloadRoute({ to: destination(id) });
      }
      void preloadCatalogs(i18n);
    });
  }, [router, queryClient, i18n]);

  const navigate = (id: string, event: MouseEvent<HTMLAnchorElement>) => {
    event.preventDefault();
    void router.navigate({ to: destination(id) });
  };
  const active = TABS.find((tab) => tab.path !== '/' && pathname.startsWith(tab.path))?.id;
  const counts: Record<string, number | undefined> = {
    jobs: badges.data?.jobs,
    messages: badges.data?.messages,
  };
  const items: TabItem[] = TABS.map((tab) => {
    const count = counts[tab.id];
    return {
      id: tab.id,
      label: t(tab.label),
      icon: tab.icon,
      href: router.history.createHref(destination(tab.id)),
      ...(count
        ? {
            count,
            countLabel: t(`nav.count.${tab.id === 'jobs' ? 'jobs' : 'messages'}`, { count }),
          }
        : {}),
    };
  });
  const tabsVisible = !main.visible && TAB_ROOTS.has(pathname);
  const contentButton = main.visible && !main.native;
  const bottom = tabsVisible ? TABBAR_HEIGHT : contentButton ? BUTTON_AREA + insets.bottom : 0;

  return (
    <div
      className="mx-auto flex min-h-dvh max-w-lg flex-col bg-bg2"
      style={{
        paddingTop: insets.top,
        paddingLeft: insets.left,
        paddingRight: insets.right,
        paddingBottom: bottom,
      }}
    >
      <main className="flex flex-1 flex-col">
        <Outlet />
      </main>
      {tabsVisible && (
        <TabBar
          items={items}
          activeId={active ?? (pathname === '/' ? 'home' : '')}
          plus={{
            id: CREATE_ID,
            label: t('nav.create'),
            href: router.history.createHref(CREATE_PATH),
          }}
          label={t('nav.sections')}
          onNavigate={navigate}
          className="mx-auto max-w-lg"
        />
      )}
      {contentButton && <ContentMainButton />}
    </div>
  );
}
