import { useQueryClient } from "@tanstack/react-query";
import { Alert, App, Button, Input, Popconfirm, Space } from "antd";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  getGetCalendarLinkQueryKey,
  useGetCalendarLink,
  useIssueCalendarLink,
} from "../../shared/api/generated/platform-bff";
import { useFormat } from "../../shared/lib/useFormat";
import { Section } from "./Section";

/**
 * Ссылка на личный календарь: подписка в календарном приложении (Яндекс, Google, Outlook) показывает сроки сотрудника
 * из «Моих задач» — названия и даты, без сумм. Секрет виден один раз, при выдаче: BFF хранит только хеш. «Сменить
 * ссылку» гасит прежнюю. Сроки обновляются, когда сотрудник работает в Платформе (снимок очереди).
 */
export function CalendarLinkSection() {
  const { t } = useTranslation("profile");
  const { date } = useFormat();
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const status = useGetCalendarLink();
  const [fresh, setFresh] = useState<string | null>(null);
  const fieldId = useId();
  const issue = useIssueCalendarLink({
    mutation: {
      onSuccess: (result) => {
        setFresh(result.url);
        void queryClient.invalidateQueries({ queryKey: getGetCalendarLinkQueryKey() });
      },
    },
  });
  const active = status.data?.active ?? false;

  const copy = () => {
    if (fresh) {
      void navigator.clipboard
        .writeText(fresh)
        .then(() => message.success(t("calendarLink.copied")));
    }
  };

  return (
    <Section
      title={t("calendarLink.title")}
      lead={t("calendarLink.lead")}
      testId="profile-calendar-link"
    >
      <Space direction="vertical" size={12} style={{ width: "100%" }}>
        {fresh ? (
          <>
            <label htmlFor={fieldId} className="pf-hint">
              {t("calendarLink.field")}
            </label>
            <Space.Compact style={{ width: "100%", maxWidth: 560 }}>
              <Input id={fieldId} readOnly value={fresh} className="pf-num" />
              <Button type="primary" onClick={copy}>
                {t("calendarLink.copy")}
              </Button>
            </Space.Compact>
            <p className="pf-hint" style={{ margin: 0 }}>
              {t("calendarLink.once")}
            </p>
          </>
        ) : active ? (
          <p style={{ margin: 0 }}>
            {t("calendarLink.active", {
              date: status.data?.issued_at ? date(status.data.issued_at) : "",
            })}
          </p>
        ) : (
          <p style={{ margin: 0 }}>{t("calendarLink.none")}</p>
        )}
        {issue.isError ? (
          <Alert type="error" showIcon role="alert" message={t("calendarLink.error")} />
        ) : null}
        {active || fresh ? (
          <Popconfirm
            title={t("calendarLink.rotateTitle")}
            okText={t("calendarLink.rotate")}
            cancelText={t("calendarLink.cancel")}
            onConfirm={() => {
              issue.mutate();
            }}
          >
            <Button loading={issue.isPending}>{t("calendarLink.rotate")}</Button>
          </Popconfirm>
        ) : (
          <Button
            type="primary"
            loading={issue.isPending}
            disabled={status.isPending}
            onClick={() => {
              issue.mutate();
            }}
          >
            {t("calendarLink.get")}
          </Button>
        )}
        <p className="pf-hint" style={{ margin: 0 }}>
          {t("calendarLink.refreshHint")}
        </p>
      </Space>
    </Section>
  );
}
