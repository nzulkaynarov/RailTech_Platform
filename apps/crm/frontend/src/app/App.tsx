import {
  AuditOutlined,
  BookOutlined,
  DashboardOutlined,
  InboxOutlined,
  QuestionCircleOutlined,
  SettingOutlined,
  TeamOutlined,
  UnorderedListOutlined,
  UserOutlined,
} from "@ant-design/icons";
import { Authenticated, Refine } from "@refinedev/core";
import {
  ErrorComponent,
  ThemedLayout,
  ThemedTitle,
  useNotificationProvider,
} from "@refinedev/antd";
import routerProvider, { CatchAllNavigate, NavigateToResource } from "@refinedev/react-router";
import { QueryClient } from "@tanstack/react-query";
import { App as AntApp, ConfigProvider } from "antd";
import ruRU from "antd/locale/ru_RU";
import "dayjs/locale/ru";
import { BrowserRouter, Outlet, Route, Routes } from "react-router";

import { AuditPage } from "../pages/audit/AuditPage";
import { DashboardPage } from "../pages/dashboard/DashboardPage";
import { GapsPage } from "../pages/gaps/GapsPage";
import { InboxPage } from "../pages/inbox/InboxPage";
import { KbPage } from "../pages/kb/KbPage";
import { SettingsPage } from "../pages/settings/SettingsPage";
import { LeadDetailPage } from "../pages/lead-detail/LeadDetailPage";
import { LeadsPage } from "../pages/leads/LeadsPage";
import { ChangePasswordPage } from "../pages/login/ChangePasswordPage";
import { LoginPage } from "../pages/login/LoginPage";
import { ProfilePage } from "../pages/profile/ProfilePage";
import { UsersPage } from "../pages/users/UsersPage";
import { t } from "../i18n/ru";
import { Header } from "./Header";
import { accessControlProvider } from "./providers/access";
import { authProvider } from "./providers/auth";
import { dataProvider } from "./providers/data";
import { i18nProvider } from "./providers/i18n";

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: true, staleTime: 5_000 } },
});

const resources = [
  { name: "inbox", list: "/inbox", meta: { label: t.nav.inbox, icon: <InboxOutlined /> } },
  {
    name: "leads",
    list: "/leads",
    show: "/leads/:id",
    meta: { label: t.nav.leads, icon: <UnorderedListOutlined /> },
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
  { name: "profile", list: "/profile", meta: { label: t.nav.profile, icon: <UserOutlined /> } },
];

function Shell() {
  return (
    <Authenticated key="shell" fallback={<CatchAllNavigate to="/login" />}>
      <ThemedLayout
        Header={Header}
        Title={(props) => <ThemedTitle {...props} text={t.app.title} />}
      >
        <Outlet />
      </ThemedLayout>
    </Authenticated>
  );
}

export function App() {
  return (
    <BrowserRouter>
      <ConfigProvider locale={ruRU}>
        <AntApp>
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
            <Routes>
              <Route element={<Shell />}>
                <Route index element={<NavigateToResource resource="inbox" />} />
                <Route path="/inbox" element={<InboxPage />} />
                <Route path="/leads" element={<LeadsPage />} />
                <Route path="/leads/:id" element={<LeadDetailPage />} />
                <Route path="/dashboard" element={<DashboardPage />} />
                <Route path="/kb" element={<KbPage />} />
                <Route path="/gaps" element={<GapsPage />} />
                <Route path="/settings" element={<SettingsPage />} />
                <Route path="/audit" element={<AuditPage />} />
                <Route path="/users" element={<UsersPage />} />
                <Route path="/profile" element={<ProfilePage />} />
                <Route path="*" element={<ErrorComponent />} />
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
