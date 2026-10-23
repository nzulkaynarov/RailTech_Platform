import { Drawer, Layout } from "antd";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Outlet, useLocation } from "react-router";

import { MODULES, findModule, isSectionActive, matchSection } from "../../modules/registry";
import type { ModuleConfig, SectionConfig } from "../../modules/types";
import { GlobalSearch } from "../../features/global-search/GlobalSearch";
import { NotificationCenter } from "../../features/notifications/NotificationCenter";
import { useNotifications } from "../../features/notifications/useNotifications";
import { useGetMenuCounters } from "../../shared/api/generated/platform-bff";
import type { MenuCounter } from "../../shared/api/generated/model";
import { pollQuery } from "../../shared/api/polling";
import { ContextPanel, ContextPanelDrawer } from "../../shared/ui/ContextPanel";
import { PlusIcon } from "../../shared/ui/icons";
import { LinkButton } from "../../shared/ui/LinkButton";
import { ModuleMenu, ModuleMenuContent, type MenuItem } from "../../shared/ui/ModuleMenu";
import { ModuleRail, type RailModule } from "../../shared/ui/ModuleRail";
import { SoonButton } from "../../shared/ui/SoonButton";
import { TopBar, type Crumb } from "../../shared/ui/TopBar";
import "../../shared/ui/shell.css";
import { canEdit, canSee } from "../access";
import { useAuth } from "../auth/useAuth";
import { AvatarMenu } from "./AvatarMenu";
import { PanelContent } from "./PanelContent";
import { usePanelSlotHost } from "./panelSlotContext";
import { usePanels } from "./usePanels";
import { useViewport } from "./useViewport";

const PANEL_ID = "pf-context-panel";
const MOBILE_BAR_HEIGHT = 60;
const HEADER_HEIGHT = 56;

function firstSection(module: ModuleConfig, canOpen: (s: SectionConfig) => boolean) {
  return module.sections.find((s) => !s.hidden && canOpen(s));
}

function isMac(): boolean {
  return typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.userAgent);
}

/**
 * Каркас Платформы (docs/architecture/platform-frontend.md §4): рейл 64 · подменю 208 · шапка 56 · основное окно · боковое окно 360.
 * Модули и разделы — из `Me.modules` и `Me.resources`; панели запоминаются по пользователю и разделу.
 * < 1200 px боковое окно — Drawer, < 768 px рейл — нижняя панель, подменю — Drawer.
 */
export function AppShell() {
  const { me } = useAuth();
  const { t } = useTranslation(["shell", "modules"]);
  const location = useLocation();
  const viewport = useViewport();
  const [menuDrawer, setMenuDrawer] = useState(false);
  const [bellOpen, setBellOpen] = useState(false);
  const searchRef = useRef<HTMLInputElement>(null);

  const match = matchSection(location.pathname, location.search);
  const panels = usePanels(me.id, match?.section);
  const { attach: attachPanelSlot, claimed: panelClaimed } = usePanelSlotHost(panels.tab);

  const railModules = useMemo(
    () => me.modules.flatMap((code) => findModule(code) ?? []),
    [me.modules],
  );
  // Подменю — активного модуля; если адрес ведёт в модуль вне роли (403), показываем первый доступный, а не чужой.
  const matchedVisible = match && railModules.some((m) => m.code === match.module.code);
  const activeModule = (matchedVisible ? match.module : undefined) ?? railModules[0] ?? MODULES[0];
  const sectionAllowed = (s: SectionConfig) => canSee(me, s.access);

  // Счётчики меню и уведомления открыты разделом «Моя очередь» (как в BFF): без него запросов нет.
  const hasQueue = canSee(me, { resource: "dashboard.queue" });
  const counters = useGetMenuCounters({ query: { ...pollQuery, enabled: hasQueue } });
  const unread = useNotifications().query;

  const unreadCount = unread.data?.unread_count ?? 0;

  // ⌘K / Ctrl+K фокусирует поиск, но не перехватывает ввод в других полях.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (!(event.metaKey || event.ctrlKey) || event.key.toLowerCase() !== "k") return;
      const target = event.target;
      if (
        target instanceof HTMLElement &&
        target !== searchRef.current &&
        (target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName))
      ) {
        return;
      }
      event.preventDefault();
      searchRef.current?.focus();
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
    };
  }, []);

  if (!activeModule) return null;

  const railItems: RailModule[] = railModules.map((module) => {
    const target = firstSection(module, sectionAllowed);
    return {
      code: module.code,
      name: module.name,
      to: target?.path ?? `/${module.code}`,
      active: matchedVisible === true && module.code === activeModule.code,
    };
  });

  const badgeFor = (item: MenuCounter | undefined) =>
    item && item.count > 0 ? { count: item.count, attention: item.attention } : undefined;
  const menuItems: MenuItem[] = activeModule.sections
    .filter((s) => !s.hidden && sectionAllowed(s))
    .map((section) => ({
      key: section.path,
      to: section.path,
      label: t(`modules:${activeModule.code}.sections.${section.key}`),
      active: isSectionActive(section, match),
      badge: badgeFor(
        counters.data?.items.find(
          (c) => c.module === activeModule.code && c.section === section.key,
        ),
      ),
    }));

  const action =
    activeModule.action && canEdit(me, activeModule.action.access) ? (
      activeModule.action.to ? (
        <LinkButton type="primary" block icon={<PlusIcon />} to={activeModule.action.to}>
          {t(`modules:${activeModule.code}.action`)}
        </LinkButton>
      ) : (
        <SoonButton type="primary" block icon={<PlusIcon />}>
          {t(`modules:${activeModule.code}.action`)}
        </SoonButton>
      )
    ) : undefined;

  const menuProps = {
    title: `${String(activeModule.order)}. ${activeModule.name}`,
    items: menuItems,
    labels: {
      nav: t("menu.nav"),
      collapse: t("menu.collapse"),
      needsAction: t("menu.needsAction"),
    },
    action,
  };

  const crumbs: Crumb[] = [];
  if (match) {
    const moduleStart = firstSection(match.module, sectionAllowed);
    crumbs.push({ label: match.module.name, to: moduleStart?.path });
    const sectionLabel = t(`modules:${match.module.code}.sections.${match.section.key}`);
    crumbs.push({
      label: sectionLabel,
      to: match.objectId ? match.section.path : undefined,
    });
    if (match.objectId) crumbs.push({ label: match.objectId });
  }

  const profile = <AvatarMenu me={me} placement={viewport.mobile ? "topRight" : "topLeft"} />;
  const tabItems = panels.tabs.map((key) => ({ key, label: t(`modules:tabs.${key}`) }));
  const panelProps = {
    id: PANEL_ID,
    label: t("panel.label"),
    tabs: tabItems,
    activeTab: panels.tab,
    onTabChange: panels.setTab,
    hideLabel: t("panel.hide"),
    onHide: () => {
      panels.setPanelOpen(false);
    },
    children: (
      <>
        <div ref={attachPanelSlot} />
        {panelClaimed ? null : (
          <PanelContent module={match?.module.code} section={match?.section.key} tab={panels.tab} />
        )}
      </>
    ),
  };

  const hasPanel = match !== undefined && sectionAllowed(match.section);
  const menuHidden = viewport.mobile ? true : !panels.menuOpen;

  return (
    <Layout style={{ height: "100dvh", overflow: "hidden" }} hasSider>
      <a href="#main-content" className="pf-skip-link">
        {t("skip")}
      </a>
      {viewport.mobile ? null : (
        <>
          <ModuleRail
            modules={railItems}
            label={t("rail.label")}
            logoLabel={t("rail.logo")}
            logoTo="/"
            profile={profile}
          />
          <ModuleMenu open={panels.menuOpen} onCollapse={panels.toggleMenu} {...menuProps} />
        </>
      )}
      <Layout style={{ minWidth: 0 }}>
        <TopBar
          crumbs={crumbs}
          labels={{
            crumbs: t("topbar.crumbs"),
            menu: t("menu.show"),
            bell:
              unreadCount > 0 ? t("topbar.bellUnread", { count: unreadCount }) : t("topbar.bell"),
            hidePanel: t("topbar.hidePanel"),
            showPanel: t("topbar.showPanel"),
            hidePanelIcon: t("panel.hide"),
            showPanelIcon: t("panel.show"),
          }}
          onShowMenu={
            menuHidden
              ? viewport.mobile
                ? () => {
                    setMenuDrawer(true);
                  }
                : panels.toggleMenu
              : undefined
          }
          search={
            <GlobalSearch
              inputRef={searchRef}
              shortcut={isMac() ? "⌘K" : "Ctrl K"}
              mobile={viewport.mobile}
            />
          }
          unread={unreadCount}
          bellTitle={t("notifications.title")}
          bellOpen={bellOpen}
          onBellOpenChange={setBellOpen}
          bellContent={
            <NotificationCenter
              variant="popover"
              onClose={() => {
                setBellOpen(false);
              }}
            />
          }
          hasPanel={hasPanel}
          panelOpen={panels.panelOpen}
          onTogglePanel={panels.togglePanel}
          panelId={PANEL_ID}
          mobile={viewport.mobile}
        />
        <Layout hasSider style={{ flex: 1, minHeight: 0 }}>
          <Layout.Content
            id="main-content"
            tabIndex={-1}
            className="pf-main"
            style={{
              overflow: "auto",
              display: "flex",
              flexDirection: "column",
              gap: 16,
              padding: viewport.mobile ? 16 : 24,
              paddingBottom: viewport.mobile ? MOBILE_BAR_HEIGHT + 16 : 24,
              outline: "none",
            }}
          >
            <Outlet />
          </Layout.Content>
          {viewport.wide && hasPanel ? (
            <ContextPanel open={panels.panelOpen} {...panelProps} />
          ) : null}
        </Layout>
      </Layout>
      {viewport.wide || !hasPanel ? null : (
        <ContextPanelDrawer
          open={panels.panelOpen}
          onClose={() => {
            panels.setPanelOpen(false);
          }}
          offsetTop={HEADER_HEIGHT}
          offsetBottom={viewport.mobile ? MOBILE_BAR_HEIGHT : 0}
          {...panelProps}
        />
      )}
      {viewport.mobile ? (
        <>
          <ModuleRail
            variant="bottom"
            modules={railItems}
            label={t("rail.label")}
            logoLabel={t("rail.logo")}
            logoTo="/"
            profile={profile}
          />
          <Drawer
            open={menuDrawer}
            placement="left"
            width={280}
            closable={false}
            onClose={() => {
              setMenuDrawer(false);
            }}
            styles={{ body: { padding: 0 } }}
            aria-label={t("menu.nav")}
          >
            <ModuleMenuContent
              {...menuProps}
              onCollapse={() => {
                setMenuDrawer(false);
              }}
              onNavigate={() => {
                setMenuDrawer(false);
              }}
            />
          </Drawer>
        </>
      ) : null}
    </Layout>
  );
}
