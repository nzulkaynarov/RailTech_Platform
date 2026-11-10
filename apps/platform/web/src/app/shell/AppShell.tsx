import { Button, Drawer, Layout } from "antd";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, Outlet, useLocation } from "react-router";

import { bridgeEntry, isStubSection } from "../../modules/bridge";
import { MODULES, matchSection } from "../../modules/registry";
import { findNavItem, visibleItems, type NavItem } from "../../modules/navigation";
import { MODULE_SETTINGS } from "../../modules/admin/moduleSettings";
import { SETTINGS_HOME } from "../../modules/admin/module";
import type { SectionConfig } from "../../modules/types";
import { SetupBanner } from "../../features/first-run/SetupBanner";
import { useLateSetupBanner, useSetupKnown } from "../../features/first-run/useSetupKnown";
import { GlobalSearch } from "../../features/global-search/GlobalSearch";
import { HelpDrawer } from "../../features/help/HelpDrawer";
import { WhatsNewNotice } from "../../features/help/WhatsNewNotice";
import { useWhatsNew } from "../../features/help/whatsNew";
import { Onboarding } from "../../features/onboarding/Onboarding";
import { NotificationCenter } from "../../features/notifications/NotificationCenter";
import {
  useNotifications,
  useReadNotifications,
} from "../../features/notifications/useNotifications";
import { useGetMenuCounters } from "../../shared/api/generated/platform-bff";
import type { MenuCounter } from "../../shared/api/generated/model";
import { usePollQuery } from "../../shared/api/polling";
import { useEventStream } from "../../shared/api/useEventStream";
import { ContextPanel, ContextPanelDrawer, ContextPanelSheet } from "../../shared/ui/ContextPanel";
import { ModuleMenu, ModuleMenuContent, type MenuItem } from "../../shared/ui/ModuleMenu";
import { ModuleRail, type RailModule } from "../../shared/ui/ModuleRail";
import { TopBar, type Crumb } from "../../shared/ui/TopBar";
import "../../shared/ui/shell.css";
import { canSee } from "../access";
import { useAuth } from "../auth/useAuth";
import { AvatarMenu } from "./AvatarMenu";
import { CreateMenu } from "./CreateMenu";
import { PanelContent } from "./PanelContent";
import { usePanelSlotHost } from "./panelSlotContext";
import { usePanels } from "./usePanels";
import { useDockFits, useViewport } from "./useViewport";

const PANEL_ID = "pf-context-panel";
const MOBILE_BAR_HEIGHT = 60;
const HEADER_HEIGHT = 56;

function isMac(): boolean {
  return typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.userAgent);
}

/**
 * Каркас Платформы (docs/architecture/platform-frontend.md §4): рейл 56 · подменю 208 · шапка 56 · основное окно · боковое окно 440/600 (Slide-over).
 * Модули и разделы — из `Me.modules` и `Me.resources`; подменю, режим и ширина окна запоминаются по пользователю, вкладка — по разделу.
 * < 1440 px подменю свёрнуто, пока пользователь его не откроет (хоткей ⌘\); < 768 px рейл — нижняя панель, подменю — Drawer; раздел с `sheetOnMobile` на телефоне
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
  const setupKnown = useSetupKnown();
  const setupBannerLate = useLateSetupBanner(setupKnown);
  const { attach: attachPanelSlot, claimed: panelClaimed } = usePanelSlotHost(panels.tab);
  const panelWidthPx = panels.panelWidth === "wide" ? 600 : 440;
  const dockFits = useDockFits(!viewport.mobile && panels.menuOpen, panelWidthPx);

  const sectionAllowed = (s: SectionConfig) => canSee(me, s.access);
  const railModules = useMemo(
    () => MODULES.filter((m) => visibleItems(m.code, (s) => canSee(me, s.access)).length > 0),
    [me],
  );
  const itemsOf = (code: (typeof MODULES)[number]["code"]) => visibleItems(code, sectionAllowed);
  const nav = match ? findNavItem(match, location.pathname, location.search) : undefined;
  // Подменю — активного модуля; если адрес ведёт в модуль вне роли (403), показываем первый доступный, а не чужой.
  const matchedVisible = match && railModules.some((m) => m.code === match.module.code);
  const activeModule =
    railModules.find((m) => m.code === nav?.module) ??
    (matchedVisible ? match.module : undefined) ??
    railModules[0] ??
    MODULES[0];

  // Счётчики меню и уведомления открыты разделом «Моя очередь» (как в BFF): без него запросов нет.
  const hasQueue = canSee(me, { resource: "dashboard.queue" });
  const poll = usePollQuery();
  const counters = useGetMenuCounters({ query: { ...poll, enabled: hasQueue } });
  // Поток подсказок BFF (SSE): события шины обновляют колокольчик, бейджи и очередь без ожидания опроса.
  useEventStream(hasQueue);
  const unread = useNotifications().query;
  const readNotes = useReadNotifications();

  const unreadCount = unread.data?.unread_count ?? 0;

  // ⌘K / Ctrl+K фокусирует поиск, но не перехватывает ввод в других полях (работает и в раскладке RU).
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (
        !(event.metaKey || event.ctrlKey) ||
        (event.key.toLowerCase() !== "k" && event.code !== "KeyK")
      ) {
        return;
      }
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

  // ⌘\ / Ctrl+\ переключает подменю, не перехватывая ввод в полях (работает и в раскладке RU). `toggleMenu`
  // стабилен (useCallback): слушатель пересоздаётся только при смене раздела или состояния подменю.
  const { toggleMenu } = panels;
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (!(event.metaKey || event.ctrlKey) || (event.key !== "\\" && event.code !== "Backslash")) {
        return;
      }
      const target = event.target;
      if (
        target instanceof HTMLElement &&
        (target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName))
      ) {
        return;
      }
      event.preventDefault();
      toggleMenu();
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
    };
  }, [toggleMenu]);

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

  const badgeOfItem = (code: string, targets: readonly string[]) => {
    const badges = targets.flatMap((ref) => {
      const [module = "", key = ""] = ref.split(".");
      const section = MODULES.find((m) => m.code === module)?.sections.find((s) => s.key === key);
      if (!section) return [];
      const counter = counters.data?.items.find((c) => c.module === module && c.section === key);
      return badgeFor(counter, code === module ? code : module, section) ?? [];
    });
    if (badges.length === 0) return undefined;
    const hint = badges.find((b) => b.hint)?.hint;
    return {
      count: badges.reduce((sum, b) => sum + b.count, 0),
      attention: badges.some((b) => b.attention),
      ...(hint ? { hint } : {}),
    };
  };
  const refsOf = (item: NavItem) => [...item.targets.map((x) => x.section), ...(item.also ?? [])];
  const itemLabel = (code: string, item: NavItem) => t(`modules:${code}.nav.${item.key}`);
  const isActiveItem = (code: string, item: NavItem) =>
    nav?.module === code && nav.item.key === item.key;

  const railItems: RailModule[] = railModules.map((module) => {
    const sections = itemsOf(module.code).map(({ item, to }) => ({
      key: `${module.code}.${item.key}`,
      path: to,
      label: itemLabel(module.code, item),
      active: isActiveItem(module.code, item),
      badge: badgeOfItem(module.code, [...new Set(refsOf(item))]),
    }));
    return {
      code: module.code,
      name: t(`modules:${module.code}.name`),
      title: t(`modules:${module.code}.title`),
      to: sections[0]?.path ?? `/${module.code}`,
      active: (nav !== undefined || matchedVisible === true) && module.code === activeModule.code,
      sections,
    };
  });

  const activeItems = itemsOf(activeModule.code);
  const menuItems: MenuItem[] = activeItems.map(({ item, to }) => ({
    key: `${activeModule.code}.${item.key}`,
    to,
    label: itemLabel(activeModule.code, item),
    active: isActiveItem(activeModule.code, item),
    badge: badgeOfItem(activeModule.code, [...new Set(refsOf(item))]),
  }));
  const activeResolved = nav
    ? activeItems.find(({ item }) => item.key === nav.item.key)
    : undefined;
  const shellTabs = activeResolved?.tabs ?? [];
  const activeItemLabel = nav ? itemLabel(nav.module, nav.item) : "";

  const action = viewport.mobile ? <CreateMenu block /> : undefined;

  // ⚙ в заголовке подменю модуля — его группа Настроек (SET-IA, HubSpot): только тем, кому Настройки видны.
  const settingsGroup = MODULE_SETTINGS[activeModule.code];
  const settingsLink =
    settingsGroup && canSee(me, { resource: "admin" })
      ? {
          to: `${SETTINGS_HOME}?group=${settingsGroup}`,
          label: t("menu.settings", { group: t(`modules:admin.groups.${settingsGroup}`) }),
        }
      : undefined;

  const menuProps = {
    // Полное имя модуля без номера (UX-оценка 2026-10-27 §6.1): «Клиенты и лиды», а не «2. CRM».
    title: t(`modules:${activeModule.code}.title`),
    ...(settingsLink ? { settings: settingsLink } : {}),
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
    const code = nav?.module ?? match.module.code;
    crumbs.push({ label: t(`modules:${code}.name`), to: itemsOf(code)[0]?.to });
    const sectionLabel = t(`modules:${match.module.code}.sections.${match.section.key}`);
    if (nav) {
      const leaf = nav.tab
        ? t(nav.tab.label ?? `modules:${code}.nav.${nav.tab.key}`)
        : sectionLabel;
      const label = itemLabel(code, nav.item);
      const deeper = leaf !== label || match.objectId !== undefined;
      crumbs.push({ label, to: deeper ? activeResolved?.to : undefined });
      if (leaf !== label) {
        crumbs.push({ label: leaf, to: match.objectId ? match.section.path : undefined });
      }
    } else {
      crumbs.push({ label: sectionLabel, to: match.objectId ? match.section.path : undefined });
    }
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
    controlLabels: {
      wide: t("panel.wide"),
      narrow: t("panel.narrow"),
      dock: t("panel.dock"),
      undock: t("panel.undock"),
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
  // Рядом — только булавкой и если помещается (≥ 1280 px и рабочей области ≥ 760 px); иначе поверх, выбор помнится.
  const panelDocked = panels.panelMode === "docked" && viewport.canDock && dockFits;
  // Окно поверх закрывает правый край основного окна: страницы, которым нужен этот край (поле ответа в переписке),
  // берут отступ из `--pf-overlay-inset`. Ширина самого основного окна не меняется.
  const overlayInset =
    !viewport.mobile && hasPanel && panels.panelOpen && !panelDocked ? panelWidthPx : 0;

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
            create={<CreateMenu />}
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
          bellExtra={
            <Button
              type="link"
              size="small"
              disabled={unreadCount === 0 || readNotes.markAllPending}
              onClick={() => {
                readNotes.markAll();
              }}
              style={{ padding: 0 }}
            >
              {t("notifications.markAll")}
            </Button>
          }
          bellContent={
            <NotificationCenter
              variant="drawer"
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
            aria-busy={setupKnown ? undefined : true}
            style={{
              // Баннер настройки не вставляется над готовым экраном: до ответа чек-листа администратора область скрыта
              // и держит место, экран под ней уже грузится (UX-1c, S10; `useSetupKnown`).
              visibility: setupKnown ? undefined : "hidden",
              overflow: "auto",
              // Полоса прокрутки не съедает ширину при появлении (Windows, 15 px; аудит 2026-10-30, S15). На телефоне
              // полосы поверх контента, а 15 px резерва в узком окне браузера сжимали шапки карточек до нуля.
              scrollbarGutter: viewport.mobile ? undefined : "stable",
              display: "flex",
              flexDirection: "column",
              gap: 16,
              padding: viewport.mobile ? 16 : 24,
              paddingBottom: viewport.mobile ? MOBILE_BAR_HEIGHT + 16 : 24,
              outline: "none",
              ["--pf-overlay-inset" as string]: `${String(overlayInset)}px`,
              // Бар несохранённого прилипает выше нижней панели модулей (< 768) или с отступом 16 px (UX-1b, S6)
              ["--pf-save-bar-offset" as string]: `${String(viewport.mobile ? MOBILE_BAR_HEIGHT + 8 : 16)}px`,
            }}
          >
            {setupBannerLate ? null : <SetupBanner />}
            {shellTabs.length > 1 ? (
              <nav className="pf-shell-tabs" aria-label={activeItemLabel}>
                {shellTabs.map((tab) => (
                  <Link
                    key={tab.key}
                    to={tab.to}
                    className="pf-shell-tab pf-focusable"
                    aria-current={nav?.tab?.key === tab.key ? "page" : undefined}
                  >
                    {t(tab.label ?? `modules:${activeModule.code}.nav.${tab.key}`)}
                  </Link>
                ))}
              </nav>
            ) : null}
            <Outlet />
            {/* Чек-лист ответил после показа экрана — баннер под экраном, готовый экран не сдвигается (UX-2b) */}
            {setupBannerLate ? <SetupBanner /> : null}
          </Layout.Content>
          {!viewport.mobile && hasPanel ? (
            <ContextPanel open={panels.panelOpen} docked={panelDocked} {...panelProps} />
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
