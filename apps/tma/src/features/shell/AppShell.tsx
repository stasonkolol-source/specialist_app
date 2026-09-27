// Оболочка экранов: safe area, таббар и нижняя кнопка (DEVELOPMENT_PLAN 0.21a). Тему клиента
// синхронизирует точка сборки (app/App.tsx): экраны S49 при старте рисуются без оболочки.
// Таббар — только на корневых экранах вкладок (SPEC §2) и скрыт, пока показана MainButton: у
// экрана с главным действием нет навигации вниз. Внутренние экраны (S48, S49b) — с «Назад».
import { useTranslation } from '@sosed/i18n';
import { useBottomButtonState, useInsets } from '@sosed/platform';
import type { TabItem } from '@sosed/ui-web';
import { Button, TabBar } from '@sosed/ui-web';
import { Outlet, useRouter, useRouterState } from '@tanstack/react-router';
import type { MouseEvent } from 'react';
import { useEffect } from 'react';

/** Высота .tabbar из ui.css (h-21): контент не уходит под таббар. */
const TABBAR_HEIGHT = 84;
const BUTTON_AREA = 76;

export const TABS = [
  { id: 'home', path: '/', icon: 'home', label: 'nav.home' },
  { id: 'jobs', path: '/jobs', icon: 'jobs', label: 'nav.jobs' },
  { id: 'messages', path: '/messages', icon: 'chat', label: 'nav.messages' },
  { id: 'profile', path: '/profile', icon: 'user', label: 'nav.profile' },
] as const;

export const CREATE_PATH = '/jobs/new';

const TAB_ROOTS: ReadonlySet<string> = new Set(TABS.map((tab) => tab.path));

export function AppShell() {
  const { t } = useTranslation();
  const router = useRouter();
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  const main = useBottomButtonState('main');
  const insets = useInsets();

  // Экраны вкладок — отдельные чанки: загрузить их сразу после старта, пока есть сеть. Иначе
  // вкладка, открытая впервые без сети (метро), не откроется совсем
  useEffect(() => {
    for (const path of [...TABS.map((tab) => tab.path), CREATE_PATH]) {
      void router.preloadRoute({ to: path });
    }
  }, [router]);

  const navigate = (href: string, event: MouseEvent<HTMLAnchorElement>) => {
    event.preventDefault();
    void router.navigate({ to: href });
  };
  const active = TABS.find((tab) => tab.path !== '/' && pathname.startsWith(tab.path))?.id;
  const items: TabItem[] = TABS.map((tab) => ({
    id: tab.id,
    label: t(tab.label),
    icon: tab.icon,
    href: router.history.createHref(tab.path),
  }));
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
          plus={{ label: t('nav.create'), href: router.history.createHref(CREATE_PATH) }}
          label={t('nav.sections')}
          onNavigate={navigate}
          className="mx-auto max-w-lg"
        />
      )}
      {contentButton && (
        <div
          className="fixed inset-x-0 bottom-0 mx-auto max-w-lg bg-bg px-4 pt-3"
          style={{ paddingBottom: insets.bottom + 12 }}
        >
          <Button full disabled={!main.enabled} onClick={main.click}>
            {main.text}
          </Button>
        </div>
      )}
    </div>
  );
}
