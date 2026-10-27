import { Alert, Button, Skeleton } from "antd";
import { useTranslation } from "react-i18next";

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
 * роли — только чтение. «Доступ: CRM · ERP» убран: роли записаны словами.
 */
export function ProfilePage() {
  const { t } = useTranslation(["profile", "audit"]);
  const { me } = useAuth();
  const profile = useGetProfile();
  const title = t("profile:title");
  useDocumentTitle(title);

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
          <IdentitySection me={me} profile={profile.data} />
          <TelegramSection profile={profile.data} />
          <Section title={t("audit:profile.notifications")} testId="profile-notifications">
            <NotificationSettings me={me} />
          </Section>
          <DeputySection profile={profile.data} />
        </>
      )}
    </div>
  );
}

export const Component = ProfilePage;
