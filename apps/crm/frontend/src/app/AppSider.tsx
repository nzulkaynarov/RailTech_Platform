import {
  ApiOutlined,
  AuditOutlined,
  BookOutlined,
  CloudServerOutlined,
  DashboardOutlined,
  DollarOutlined,
  ExperimentOutlined,
  FundOutlined,
  HeartOutlined,
  InboxOutlined,
  QuestionCircleOutlined,
  SettingOutlined,
  ShopOutlined,
  SnippetsOutlined,
  TeamOutlined,
  UnorderedListOutlined,
  MessageOutlined,
} from "@ant-design/icons";
import { useThemedLayoutContext } from "@refinedev/antd";
import { Badge, Drawer, Grid, Layout, Menu, theme } from "antd";
import type { MenuProps } from "antd";
import type { ReactNode } from "react";
import { Link, useLocation } from "react-router";

import { useKbGaps } from "../api/adminQueries";
import { useInbox, useMe, usePermissionsQuery } from "../api/queries";
import { openHandoffCount } from "../domain/sla";
import { t } from "../i18n/ru";
import { AppTitle } from "./AppTitle";
import { type NavKey, navKeyOf, visibleNav } from "./navigation";

const ICONS: Record<NavKey, ReactNode> = {
  inbox: <InboxOutlined />,
  leads: <UnorderedListOutlined />,
  clients: <ShopOutlined />,
  deals: <FundOutlined />,
  dashboard: <DashboardOutlined />,
  spend: <DollarOutlined />,
  kb: <BookOutlined />,
  gaps: <QuestionCircleOutlined />,
  sandbox: <MessageOutlined />,
  settings: <SettingOutlined />,
  templates: <SnippetsOutlined />,
  users: <TeamOutlined />,
  integrations: <ApiOutlined />,
  models: <ExperimentOutlined />,
  system: <HeartOutlined />,
  backups: <CloudServerOutlined />,
  audit: <AuditOutlined />,
};

/** Счётчик справа от подписи пункта (не поверх иконки): число видно и в узком меню. */
function NavCount({ count, srText }: { count: number; srText: string }) {
  if (!count) return null;
  return (
    <>
      <Badge count={count} size="small" className="nav-count" aria-hidden />
      <span className="sr-only">{srText.replace("{count}", String(count))}</span>
    </>
  );
}

/** Открытые передачи — тот же запрос инбокса, его перечитывает SSE; своего опроса нет. */
function InboxCount() {
  const { data } = useInbox();
  return <NavCount count={openHandoffCount(data)} srText={t.inbox.navCount} />;
}

function GapsCount() {
  const { data } = useKbGaps({ status: "open", limit: 1 });
  return <NavCount count={data?.total ?? 0} srText={t.nav.gapsCount} />;
}

const COUNTS: Partial<Record<NavKey, () => ReactNode>> = {
  inbox: () => <InboxCount />,
  gaps: () => <GapsCount />,
};

function useNavItems(collapsed: boolean): NonNullable<MenuProps["items"]> {
  const perms = usePermissionsQuery();
  const me = useMe();
  const groups = visibleNav(perms.data, me.data?.ui_mode);
  const item = (key: NavKey) => ({
    key,
    icon: ICONS[key],
    label: (
      <Link to={`/${key}`} className="nav-link">
        <span className="nav-label">{t.nav[key]}</span>
        {COUNTS[key]?.()}
      </Link>
    ),
  });
  if (collapsed) {
    // Свёрнутое меню: заголовки групп не помещаются — группы разделены линией.
    return groups.flatMap((g, i) => [
      ...(i ? [{ type: "divider" as const, key: `d-${g.key}` }] : []),
      ...g.items.map(item),
    ]);
  }
  return groups.map((g) => ({
    type: "group" as const,
    key: g.key,
    label: g.title,
    children: g.items.map(item),
  }));
}

function NavMenu({ collapsed, onNavigate }: { collapsed: boolean; onNavigate?: () => void }) {
  const { pathname } = useLocation();
  const selected = navKeyOf(pathname);
  return (
    <nav aria-label={t.common.mainNav}>
      <Menu
        mode="inline"
        className="app-nav"
        selectedKeys={selected ? [selected] : []}
        items={useNavItems(collapsed)}
        onClick={() => onNavigate?.()}
      />
    </nav>
  );
}

/**
 * Сайдбар с группами «Работа · Аналитика · Бот · Администрирование». Свой, а не `ThemedSider`:
 * у того нет заголовков групп и счётчиков справа от подписи. Мобильная панель — тот же
 * контекст `ThemedLayout`, кнопка открытия — в шапке.
 */
export function AppSider() {
  const { token } = theme.useToken();
  const screens = Grid.useBreakpoint();
  const { siderCollapsed, setSiderCollapsed, mobileSiderOpen, setMobileSiderOpen } =
    useThemedLayoutContext();
  const title = (collapsed: boolean) => (
    <div className="app-sider-title" style={{ background: token.colorBgElevated }}>
      <AppTitle collapsed={collapsed} />
    </div>
  );
  if (screens.lg === false) {
    const close = () => {
      setMobileSiderOpen(false);
    };
    return (
      <Drawer
        open={mobileSiderOpen}
        onClose={close}
        placement="left"
        closable={false}
        width={240}
        styles={{ body: { padding: 0 } }}
      >
        {title(false)}
        <NavMenu collapsed={false} onNavigate={close} />
      </Drawer>
    );
  }
  return (
    <Layout.Sider
      collapsible
      collapsed={siderCollapsed}
      onCollapse={setSiderCollapsed}
      width={232}
      collapsedWidth={80}
      theme="light"
      className="app-sider"
      style={{ background: token.colorBgContainer }}
    >
      {title(siderCollapsed)}
      <NavMenu collapsed={siderCollapsed} />
    </Layout.Sider>
  );
}
