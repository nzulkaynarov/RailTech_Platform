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
 * роли — только чтение. Вкладки «Все разделы · Личные данные · Уведомления · Замещение» — в адресе `?part=`.
 */
const PARTS = ["all", "general", "notifications", "deputy"] as const;
type Part = (typeof PARTS)[number];
const PART_LABEL: Record<Part, string> = {
  all: "profile:tabs.all",
  general: "profile:tabs.general",
  notifications: "audit:profile.notifications",
  deputy: "profile:deputy.title",
};

export function ProfilePage() {
  const { t } = useTranslation(["profile", "audit"]);
  const { me } = useAuth();
  const profile = useGetProfile();
  const [params, setParams] = useSearchParams();
  const title = t("profile:title");
  useDocumentTitle(title);

  const asked = params.get("part");
  const part = PARTS.includes(asked as Part) ? (asked as Part) : "all";

  const onTabChange = (key: string) => {
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (key === "all") {
          next.delete("part");
        } else {
          next.set("part", key);
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
            activeKey={part}
            onChange={onTabChange}
            destroyOnHidden
            items={PARTS.map((key) => ({
              key,
              label: t(PART_LABEL[key]),
              children: (
                <div className="pf-profile-part">
                  {key === "all" || key === "general" ? (
                    <IdentitySection me={me} profile={profile.data} />
                  ) : null}
                  {key === "all" || key === "general" || key === "notifications" ? (
                    <TelegramSection profile={profile.data} />
                  ) : null}
                  {key === "all" || key === "notifications" ? (
                    <Section
                      title={t("audit:profile.notifications")}
                      testId="profile-notifications"
                    >
                      <NotificationSettings me={me} />
                    </Section>
                  ) : null}
                  {key === "all" || key === "deputy" ? (
                    <DeputySection profile={profile.data} />
                  ) : null}
                </div>
              ),
            }))}
          />
        </>
      )}
    </div>
  );
}

export const Component = ProfilePage;
