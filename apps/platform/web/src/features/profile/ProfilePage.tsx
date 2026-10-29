import { Alert, Button, Skeleton, Tabs } from "antd";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router";

import { useAuth } from "../../app/auth/useAuth";
import { useGetProfile } from "../../shared/api/generated/platform-bff";
import { useDocumentTitle } from "../../shared/lib/useDocumentTitle";
import { PageHeader } from "../../shared/ui/PageHeader";
import { NotificationSettings } from "../profile-notifications/NotificationSettings";
import { DeputySection } from "./DeputySection";
import { IdentitySection } from "./IdentitySection";
import { Section } from "./Section";
import { TelegramSection } from "./TelegramSection";

import "./profile.css";

/**
 * Профиль `/me` (W15-H6, UX-оценка P1-3): страница, а не окно. Фото, личные данные, «Telegram для уведомлений»,
 * подписки на уведомления бота и замещение. Данные принадлежат CRM (ADR-0015), сотрудник правит только свои; должность и
 * роли — только чтение. Вкладки синхронизированы с URL (`?viewTab=`).
 */
export function ProfilePage() {
  const { t } = useTranslation(["profile", "audit"]);
  const { me } = useAuth();
  const profile = useGetProfile();
  const [params, setParams] = useSearchParams();
  const title = t("profile:title");
  useDocumentTitle(title);

  const viewTab = params.get("viewTab") ?? "all";

  const onTabChange = (key: string) => {
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (key === "all") {
          next.delete("viewTab");
        } else {
          next.set("viewTab", key);
        }
        return next;
      },
      { replace: true },
    );
  };

  return (
    <div className="pf-profile">
      <PageHeader title={title} subtitle={me.email} />
      {profile.isPending ? (
        <Skeleton active paragraph={{ rows: 8 }} />
      ) : profile.isError ? (
        <Alert
          type="error"
          showIcon
          role="alert"
          message={t("profile:loadError")}
          action={
            <Button
              size="small"
              onClick={() => {
                void profile.refetch();
              }}
            >
              {t("profile:retry")}
            </Button>
          }
        />
      ) : (
        <>
          <Tabs
            activeKey={viewTab}
            onChange={onTabChange}
            items={[
              {
                key: "all",
                label: t("profile:tabs.all", "Все разделы"),
              },
              {
                key: "general",
                label: t("profile:tabs.general", "Личные данные"),
              },
              {
                key: "notifications",
                label: t("audit:profile.notifications", "Уведомления"),
              },
              {
                key: "deputy",
                label: t("profile:deputy.title", "Замещение"),
              },
            ]}
          />
          {viewTab === "all" || viewTab === "general" ? (
            <IdentitySection me={me} profile={profile.data} />
          ) : null}
          {viewTab === "all" || viewTab === "general" || viewTab === "notifications" ? (
            <TelegramSection profile={profile.data} />
          ) : null}
          {viewTab === "all" || viewTab === "notifications" ? (
            <Section title={t("audit:profile.notifications")} testId="profile-notifications">
              <NotificationSettings me={me} />
            </Section>
          ) : null}
          {viewTab === "all" || viewTab === "deputy" ? (
            <DeputySection profile={profile.data} />
          ) : null}
        </>
      )}
    </div>
  );
}

export const Component = ProfilePage;
