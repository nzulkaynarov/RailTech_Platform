import { Drawer, Layout } from "antd";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Outlet, useLocation } from "react-router";

import { MODULE_ACTION_WHEN, bridgeEntry, isStubSection } from "../../modules/bridge";
import { MODULES, findModule, isSectionActive, matchSection } from "../../modules/registry";
import type { ModuleConfig, SectionConfig } from "../../modules/types";
import { SetupBanner } from "../../features/first-run/SetupBanner";
import { useSetupPending } from "../../features/first-run/useSetupPending";
import { GlobalSearch } from "../../features/global-search/GlobalSearch";
import { HelpDrawer } from "../../features/help/HelpDrawer";
import { WhatsNewNotice } from "../../features/help/WhatsNewNotice";
import { useWhatsNew } from "../../features/help/whatsNew";
import { Onboarding } from "../../features/onboarding/Onboarding";
import { NotificationCenter } from "../../features/notifications/NotificationCenter";
import { useNotifications } from "../../features/notifications/useNotifications";
import { useGetMenuCounters } from "../../shared/api/generated/platform-bff";
import type { MenuCounter } from "../../shared/api/generated/model";
import { usePollQuery } from "../../shared/api/polling";
import { useEventStream } from "../../shared/api/useEventStream";
import { ContextPanel, ContextPanelDrawer, ContextPanelSheet } from "../../shared/ui/ContextPanel";
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

function firstSection(module: ModuleConfig, inMenu: (s: SectionConfig) => boolean) {
  return module.sections.find(inMenu);
}

function isMac(): boolean {
  return typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.userAgent);
}

/**
 * Каркас Платформы (docs/architecture/platform-frontend.md §4): рейл 64 · подменю 208 · шапка 56 · основное окно · боковое окно 360.
 * Модули и разделы — из `Me.modules` и `Me.resources`; панели запоминаются по пользователю и разделу.
 * < 1200 px боковое окно — Drawer, < 768 px рейл — нижняя панель, подменю — Drawer; раздел с `sheetOnMobile` на телефоне
 * показывает боковое окно листом на весь экран (B-020).
 */
export function AppShell() {
  const { me } = useAuth();
  const { t } = useTranslation(["shell", "modules", "bridge"]);
  const location = useLocation();
  const viewport = useViewport();
  const [menuDrawer, setMenuDrawer] = useState(false);
  const [bellOpen, setBellOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const { fresh: helpFresh } = useWhatsNew();
  const searchRef = useRef<HTMLInputElement>(null);

  const match = matchSection(location.pathname, location.search);
  // В списках и таблицах боковое окно закрыто по умолчанию (открывается по ?panel=open);
  // на карточке конкретного объекта (:id) открыто на широком экране, если не закрыто явно.
  const panels = usePanels(
    me.id,
    match?.section,
    Boolean(match?.objectId && !isStubSection(match.module.code, match.section.key)),
  );
  const setupPending = useSetupPending();
  const { attach: attachPanelSlot, claimed: panelClaimed } = usePanelSlotHost(panels.tab);

  const railModules = useMemo(
    () => me.modules.flatMap((code) => findModule(code) ?? []),
    [me.modules],
  );
  const sectionAllowed = (s: SectionConfig) => canSee(me, s.access);
  // Пункт подменю: не скрыт, виден роли (`menuAccess` уже доступа к адресу) и его условие выполнено (W15-H4).
  const inMenu = (s: SectionConfig) =>
    !s.hidden &&
    canSee(me, s.menuAccess ?? s.access) &&
    (s.showWhile !== "setupPending" || setupPending);
  // Раздел открыт, но его пункта в своём модуле у сотрудника нет: меню и крошки — там, где раздел для него живёт
  // (`menuHome`; база знаний для администратора — Настройки · Telegram-бот).
  const homeOf = (() => {
    const home = match?.section.menuHome;
    if (!match || !home || inMenu(match.section) || !sectionAllowed(match.section))
      return undefined;
    const module = railModules.find((m) => m.code === home.module);
    const section = module?.sections.find((s) => s.key === home.section);
    return module && section ? { module, section } : undefined;
  })();
  // Подменю — активного модуля; если адрес ведёт в модуль вне роли (403), показываем первый доступный, а не чужой.
  const matchedVisible = match && railModules.some((m) => m.code === match.module.code);
  const activeModule =
    homeOf?.module ?? (matchedVisible ? match.module : undefined) ?? railModules[0] ?? MODULES[0];

  // Счётчики меню и уведомления открыты разделом «Моя очередь» (как в BFF): без него запросов нет.
  const hasQueue = canSee(me, { resource: "dashboard.queue" });
  const poll = usePollQuery();
  const counters = useGetMenuCounters({ query: { ...poll, enabled: hasQueue } });
  // Поток подсказок BFF (SSE): события шины обновляют колокольчик, бейджи и очередь без ожидания опроса.
  useEventStream(hasQueue);
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

  // «?» открывает окно помощи, но не перехватывает ввод в полях (как ⌘K).
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "?" || event.metaKey || event.ctrlKey || event.altKey) return;
      const target = event.target;
      if (
        target instanceof HTMLElement &&
        (target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName))
      ) {
        return;
      }
      event.preventDefault();
      setHelpOpen(true);
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
    };
  }, []);

  // ⌘\ / Ctrl+\ переключает подменю (toggleMenu), не перехватывая ввод в полях
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (!(event.metaKey || event.ctrlKey) || event.key !== "\\") return;
      const target = event.target;
      if (
        target instanceof HTMLElement &&
        (target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName))
      ) {
        return;
      }
      event.preventDefault();
      panels.toggleMenu();
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
    };
  }, [panels]);

  if (!activeModule) return null;

  const badgeFor = (item: MenuCounter | undefined, moduleCode: string, section: SectionConfig) => {
    if (!item || item.count <= 0) return undefined;
    // Раздел-заглушка (W15-H1): бейдж только с нейтральной подсказкой «ещё в старой системе: N» (названия систем — на самой заглушке), если то же число видно в старой системе;
    // иначе бейджа нет — рядом с честной заглушкой число без дела только путает.
    if (isStubSection(moduleCode, section.key)) {
      const entry = bridgeEntry(moduleCode, section.key);
      if (!entry?.legacyCount || !entry.legacy) return undefined;
      return {
        count: item.count,
        attention: false,
        hint: t("bridge:badgeHint", { count: item.count }),
      };
    }
    return { count: item.count, attention: item.attention };
  };

  const railItems: RailModule[] = railModules.map((module) => {
    const target = firstSection(module, inMenu);
    const sections = module.sections.filter(inMenu).map((s) => ({
      key: s.path,
      path: s.path,
      label: t(`modules:${module.code}.sections.${s.key}`),
      active: homeOf ? homeOf.section.key === s.key : isSectionActive(s, match),
      badge: badgeFor(
        counters.data?.items.find((c) => c.module === module.code && c.section === s.key),
        module.code,
        s,
      ),
    }));
    return {
      code: module.code,
      name: t(`modules:${module.code}.name`),
      title: t(`modules:${module.code}.title`),
      to: target?.path ?? `/${module.code}`,
      active:
        (homeOf !== undefined || matchedVisible === true) && module.code === activeModule.code,
      sections,
    };
  });

  const menuItems: MenuItem[] = activeModule.sections.filter(inMenu).map((section) => ({
    key: section.path,
    to: section.path,
    label: t(`modules:${activeModule.code}.sections.${section.key}`),
    active: homeOf ? homeOf.section.key === section.key : isSectionActive(section, match),
    badge: badgeFor(
      counters.data?.items.find((c) => c.module === activeModule.code && c.section === section.key),
      activeModule.code,
      section,
    ),
  }));

  const action =
    activeModule.action && canEdit(me, activeModule.action.access) ? (
      activeModule.action.to ? (
        <LinkButton type="primary" block icon={<PlusIcon />} to={activeModule.action.to}>
          {t(`modules:${activeModule.code}.action`)}
        </LinkButton>
      ) : (
        <SoonButton
          type="primary"
          block
          icon={<PlusIcon />}
          hint={t(MODULE_ACTION_WHEN[activeModule.code] === "soon" ? "soon" : "soonPilot")}
        >
          {t(`modules:${activeModule.code}.action`)}
        </SoonButton>
      )
    ) : undefined;

  const menuProps = {
    // Полное имя модуля без номера (UX-оценка 2026-10-27 §6.1): «Клиенты и лиды», а не «2. CRM».
    title: t(`modules:${activeModule.code}.title`),
    items: menuItems,
    labels: {
      nav: t("menu.nav"),
      collapse: t("menu.collapse"),
      needsAction: t("menu.needsAction"),
    },
    action,
  };

  const crumbs: Crumb[] = [];
  if (match && homeOf) {
    crumbs.push({
      label: t(`modules:${homeOf.module.code}.name`),
      to: firstSection(homeOf.module, inMenu)?.path,
    });
    crumbs.push({
      label: t(`modules:${homeOf.module.code}.sections.${homeOf.section.key}`),
      to: homeOf.section.path,
    });
    crumbs.push({ label: t(`modules:${match.module.code}.sections.${match.section.key}`) });
  } else if (match) {
    const moduleStart = firstSection(match.module, inMenu);
    crumbs.push({ label: t(`modules:${match.module.code}.name`), to: moduleStart?.path });
    const sectionLabel = t(`modules:${match.module.code}.sections.${match.section.key}`);
    crumbs.push({
      label: sectionLabel,
      to: match.objectId ? match.section.path : undefined,
    });
    if (match.objectId) crumbs.push({ label: match.objectId });
  }

  const openHelp = () => {
    setHelpOpen(true);
  };
  const profile = (
    <AvatarMenu me={me} placement={viewport.mobile ? "topRight" : "topLeft"} onHelp={openHelp} />
  );
  // Ключ раздела для статьи «К этому разделу»: `crm.leads`; профиль — `me`; сам раздел помощи — `help`.
  const helpSection = match
    ? `${match.module.code}.${match.section.key}`
    : location.pathname.startsWith("/me")
      ? "me"
      : location.pathname.startsWith("/help")
        ? "help"
        : undefined;
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
    panelMode: panels.panelMode,
    onModeChange: panels.setPanelMode,
    panelWidth: panels.panelWidth,
    onWidthChange: panels.setPanelWidth,
    canDock: viewport.canDock,
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
            menuOpen={panels.menuOpen}
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
          help={{
            label: helpFresh ? t("help:whatsNew.helpFresh") : t("topbar.help"),
            open: helpOpen,
            onClick: openHelp,
            fresh: helpFresh,
          }}
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
            <SetupBanner />
            <Outlet />
          </Layout.Content>
          {!viewport.mobile && hasPanel ? (
            <ContextPanel open={panels.panelOpen} {...panelProps} />
          ) : null}
        </Layout>
      </Layout>
      {viewport.mobile && hasPanel && match.section.sheetOnMobile ? (
        <ContextPanelSheet
          open={panels.panelOpen}
          onClose={() => {
            panels.setPanelOpen(false);
          }}
          title={t(`modules:tabs.${panels.tab}`)}
          closeLabel={t("panel.close")}
          {...panelProps}
        />
      ) : viewport.mobile && hasPanel ? (
        <ContextPanelDrawer
          open={panels.panelOpen}
          onClose={() => {
            panels.setPanelOpen(false);
          }}
          offsetTop={HEADER_HEIGHT}
          offsetBottom={MOBILE_BAR_HEIGHT}
          {...panelProps}
        />
      ) : null}
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
      <HelpDrawer
        open={helpOpen}
        onClose={() => {
          setHelpOpen(false);
        }}
        {...(helpSection ? { sectionKey: helpSection } : {})}
      />
      <Onboarding />
      <WhatsNewNotice />
    </Layout>
  );
}
