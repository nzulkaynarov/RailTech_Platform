import { Authenticated, Refine } from "@refinedev/core";
import { ThemedLayout, useNotificationProvider } from "@refinedev/antd";
import routerProvider, { CatchAllNavigate, DocumentTitleHandler } from "@refinedev/react-router";
import { QueryClient } from "@tanstack/react-query";
import { App as AntApp, ConfigProvider } from "antd";
import ruRU from "antd/es/locale/ru_RU";
import "dayjs/locale/ru";
import { BrowserRouter, Outlet, Route, Routes } from "react-router";

import { AuditPage } from "../pages/audit/AuditPage";
import { BackupsPage } from "../pages/backups/BackupsPage";
import { ModelsPage } from "../pages/models/ModelsPage";
import { SandboxPage } from "../pages/sandbox/SandboxPage";
import { SpendPage } from "../pages/spend/SpendPage";
import { ClientDetailPage } from "../pages/clients/ClientDetailPage";
import { ClientsPage } from "../pages/clients/ClientsPage";
import { DashboardPage } from "../pages/dashboard/DashboardPage";
import { DealsPage } from "../pages/deals/DealsPage";
import { GapsPage } from "../pages/gaps/GapsPage";
import { InboxPage } from "../pages/inbox/InboxPage";
import { IntegrationsPage } from "../pages/integrations/IntegrationsPage";
import { ReplyTemplatesPage } from "../pages/templates/ReplyTemplatesPage";
import { HomeRedirect } from "./HomeRedirect";
import { KbPage } from "../pages/kb/KbPage";
import { SettingsPage } from "../pages/settings/SettingsPage";
import { SystemPage } from "../pages/system/SystemPage";
import { LeadDetailPage } from "../pages/lead-detail/LeadDetailPage";
import { LeadsPage } from "../pages/leads/LeadsPage";
import { ChangePasswordPage } from "../pages/login/ChangePasswordPage";
import { LoginPage } from "../pages/login/LoginPage";
import { ProfilePage } from "../pages/profile/ProfilePage";
import { SetupPage } from "../pages/setup/SetupPage";
import { UsersPage } from "../pages/users/UsersPage";
import { t } from "../i18n/ru";
import { AppSider } from "./AppSider";
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

// Ресурсы Refine — для заголовков вкладок и `useCan`; меню строит `AppSider` по `navigation.ts`.
const resources = [
  { name: "inbox", list: "/inbox", meta: { label: t.nav.inbox } },
  { name: "leads", list: "/leads", show: "/leads/:id", meta: { label: t.nav.leads } },
  { name: "clients", list: "/clients", show: "/clients/:id", meta: { label: t.nav.clients } },
  { name: "deals", list: "/deals", meta: { label: t.nav.deals } },
  { name: "dashboard", list: "/dashboard", meta: { label: t.nav.dashboard } },
  { name: "spend", list: "/spend", meta: { label: t.nav.spend } },
  { name: "kb", list: "/kb", meta: { label: t.nav.kb } },
  { name: "gaps", list: "/gaps", meta: { label: t.nav.gaps } },
  { name: "sandbox", list: "/sandbox", meta: { label: t.nav.sandbox } },
  { name: "settings", list: "/settings", meta: { label: t.nav.settings } },
  { name: "templates", list: "/templates", meta: { label: t.nav.templates } },
  { name: "users", list: "/users", meta: { label: t.nav.users } },
  { name: "integrations", list: "/integrations", meta: { label: t.nav.integrations } },
  { name: "models", list: "/models", meta: { label: t.nav.models } },
  { name: "system", list: "/system", meta: { label: t.nav.system } },
  { name: "backups", list: "/backups", meta: { label: t.nav.backups } },
  { name: "audit", list: "/audit", meta: { label: t.nav.audit } },
  { name: "profile", list: "/profile", meta: { label: t.nav.profile } },
];

/** Тосты в постоянном live-регионе — озвучиваются скринридером (WCAG 4.1.3). */
const messageConfig = { getContainer: ensureLiveRegion };

function Shell() {
  return (
    <Authenticated key="shell" fallback={<CatchAllNavigate to="/login" />}>
      <div className="app-shell">
        <ThemedLayout Header={Header} Title={AppTitle} Sider={AppSider}>
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
                  path="/deals"
                  element={
                    <RouteGuard resource="deals">
                      <DealsPage />
                    </RouteGuard>
                  }
                />
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
                  path="/sandbox"
                  element={
                    <RouteGuard resource="sandbox">
                      <SandboxPage />
                    </RouteGuard>
                  }
                />
                <Route
                  path="/spend"
                  element={
                    <RouteGuard resource="spend">
                      <SpendPage />
                    </RouteGuard>
                  }
                />
                <Route
                  path="/models"
                  element={
                    <RouteGuard resource="models">
                      <ModelsPage />
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
                  path="/backups"
                  element={
                    <RouteGuard resource="backups">
                      <BackupsPage />
                    </RouteGuard>
                  }
                />
                <Route
                  path="/templates"
                  element={
                    <RouteGuard resource="templates">
                      <ReplyTemplatesPage />
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
                <Route
                  path="/system"
                  element={
                    <RouteGuard resource="system">
                      <SystemPage />
                    </RouteGuard>
                  }
                />
                <Route path="/profile" element={<ProfilePage />} />
                <Route path="*" element={<NotFound />} />
              </Route>
              <Route path="/login" element={<LoginPage />} />
              <Route path="/setup" element={<SetupPage />} />
              <Route path="/change-password" element={<ChangePasswordPage />} />
            </Routes>
          </Refine>
        </AntApp>
      </ConfigProvider>
    </BrowserRouter>
  );
}
