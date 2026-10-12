import {
  ApiOutlined,
  AuditOutlined,
  BookOutlined,
  DashboardOutlined,
  QuestionCircleOutlined,
  SettingOutlined,
  ShopOutlined,
  TeamOutlined,
  UnorderedListOutlined,
  UserOutlined,
} from "@ant-design/icons";
import { Authenticated, Refine } from "@refinedev/core";
import { ThemedLayout, useNotificationProvider } from "@refinedev/antd";
import routerProvider, { CatchAllNavigate, DocumentTitleHandler } from "@refinedev/react-router";
import { QueryClient } from "@tanstack/react-query";
import { App as AntApp, ConfigProvider } from "antd";
import ruRU from "antd/es/locale/ru_RU";
import "dayjs/locale/ru";
import { BrowserRouter, Outlet, Route, Routes } from "react-router";

import { AuditPage } from "../pages/audit/AuditPage";
import { ClientDetailPage } from "../pages/clients/ClientDetailPage";
import { ClientsPage } from "../pages/clients/ClientsPage";
import { DashboardPage } from "../pages/dashboard/DashboardPage";
import { GapsPage } from "../pages/gaps/GapsPage";
import { InboxNavIcon } from "../components/InboxNavIcon";
import { InboxPage } from "../pages/inbox/InboxPage";
import { IntegrationsPage } from "../pages/integrations/IntegrationsPage";
import { HomeRedirect } from "./HomeRedirect";
import { KbPage } from "../pages/kb/KbPage";
import { SettingsPage } from "../pages/settings/SettingsPage";
import { LeadDetailPage } from "../pages/lead-detail/LeadDetailPage";
import { LeadsPage } from "../pages/leads/LeadsPage";
import { ChangePasswordPage } from "../pages/login/ChangePasswordPage";
import { LoginPage } from "../pages/login/LoginPage";
import { ProfilePage } from "../pages/profile/ProfilePage";
import { UsersPage } from "../pages/users/UsersPage";
import { t } from "../i18n/ru";
import { AppTitle } from "./AppTitle";
import { documentTitle } from "./documentTitle";
import { Header } from "./Header";
import { ensureLiveRegion } from "./liveRegion";
import { NotFound, RouteGuard } from "./RouteGuard";
import { accessControlProvider } from "./providers/access";
import { authProvider } from "./providers/auth";
import { dataProvider } from "./providers/data";
import { i18nProvider } from "./providers/i18n";
import { appTheme } from "./theme";

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: true, staleTime: 5_000 } },
});

const resources = [
  { name: "inbox", list: "/inbox", meta: { label: t.nav.inbox, icon: <InboxNavIcon /> } },
  {
    name: "leads",
    list: "/leads",
    show: "/leads/:id",
    meta: { label: t.nav.leads, icon: <UnorderedListOutlined /> },
  },
  {
    name: "clients",
    list: "/clients",
    show: "/clients/:id",
    meta: { label: t.nav.clients, icon: <ShopOutlined /> },
  },
  {
    name: "dashboard",
    list: "/dashboard",
    meta: { label: t.nav.dashboard, icon: <DashboardOutlined /> },
  },
  { name: "kb", list: "/kb", meta: { label: t.nav.kb, icon: <BookOutlined /> } },
  { name: "gaps", list: "/gaps", meta: { label: t.nav.gaps, icon: <QuestionCircleOutlined /> } },
  {
    name: "settings",
    list: "/settings",
    meta: { label: t.nav.settings, icon: <SettingOutlined /> },
  },
  { name: "audit", list: "/audit", meta: { label: t.nav.audit, icon: <AuditOutlined /> } },
  { name: "users", list: "/users", meta: { label: t.nav.users, icon: <TeamOutlined /> } },
  {
    name: "integrations",
    list: "/integrations",
    meta: { label: t.nav.integrations, icon: <ApiOutlined /> },
  },
  { name: "profile", list: "/profile", meta: { label: t.nav.profile, icon: <UserOutlined /> } },
];

/** Тосты в постоянном live-регионе — озвучиваются скринридером (WCAG 4.1.3). */
const messageConfig = { getContainer: ensureLiveRegion };

function Shell() {
  return (
    <Authenticated key="shell" fallback={<CatchAllNavigate to="/login" />}>
      <div className="app-shell">
        <ThemedLayout Header={Header} Title={AppTitle}>
          <Outlet />
        </ThemedLayout>
      </div>
    </Authenticated>
  );
}

export function App() {
  return (
    <BrowserRouter>
      <ConfigProvider locale={ruRU} theme={appTheme}>
        <AntApp message={messageConfig}>
          <Refine
            routerProvider={routerProvider}
            dataProvider={dataProvider}
            i18nProvider={i18nProvider}
            authProvider={authProvider}
            accessControlProvider={accessControlProvider(queryClient)}
            notificationProvider={useNotificationProvider}
            resources={resources}
            options={{
              reactQuery: { clientConfig: queryClient },
              disableTelemetry: true,
              syncWithLocation: false,
            }}
          >
            <DocumentTitleHandler handler={documentTitle} />
            <Routes>
              <Route element={<Shell />}>
                <Route index element={<HomeRedirect />} />
                <Route
                  path="/inbox"
                  element={
                    <RouteGuard resource="inbox">
                      <InboxPage />
                    </RouteGuard>
                  }
                />
                <Route path="/leads" element={<LeadsPage />} />
                <Route path="/leads/:id" element={<LeadDetailPage />} />
                <Route path="/clients" element={<ClientsPage />} />
                <Route path="/clients/:id" element={<ClientDetailPage />} />
                <Route
                  path="/dashboard"
                  element={
                    <RouteGuard resource="dashboard">
                      <DashboardPage />
                    </RouteGuard>
                  }
                />
                <Route
                  path="/kb"
                  element={
                    <RouteGuard resource="kb">
                      <KbPage />
                    </RouteGuard>
                  }
                />
                <Route
                  path="/gaps"
                  element={
                    <RouteGuard resource="gaps">
                      <GapsPage />
                    </RouteGuard>
                  }
                />
                <Route
                  path="/settings"
                  element={
                    <RouteGuard resource="settings">
                      <SettingsPage />
                    </RouteGuard>
                  }
                />
                <Route
                  path="/audit"
                  element={
                    <RouteGuard resource="audit">
                      <AuditPage />
                    </RouteGuard>
                  }
                />
                <Route
                  path="/users"
                  element={
                    <RouteGuard resource="users">
                      <UsersPage />
                    </RouteGuard>
                  }
                />
                <Route
                  path="/integrations"
                  element={
                    <RouteGuard resource="integrations">
                      <IntegrationsPage />
                    </RouteGuard>
                  }
                />
                <Route path="/profile" element={<ProfilePage />} />
                <Route path="*" element={<NotFound />} />
              </Route>
              <Route path="/login" element={<LoginPage />} />
              <Route path="/change-password" element={<ChangePasswordPage />} />
            </Routes>
          </Refine>
        </AntApp>
      </ConfigProvider>
    </BrowserRouter>
  );
}
