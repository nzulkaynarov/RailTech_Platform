import { useQueryClient } from "@tanstack/react-query";
import { Alert, App, Button, Skeleton, Switch } from "antd";
import { useId } from "react";
import { useTranslation } from "react-i18next";

import { canSee } from "../../app/access";
import type { Me } from "../../shared/api/generated/model";
import {
  getGetNotificationSettingsQueryKey,
  useGetNotificationSettings,
  useSendTestNotification,
  useUpdateNotificationSettings,
} from "../../shared/api/generated/platform-bff";
import { useFormat } from "../../shared/lib/useFormat";
import { testErrorKey } from "./errors";

function Row({
  id,
  label,
  hint,
  checked,
  disabled,
  loading,
  onChange,
}: {
  id: string;
  label: string;
  hint: string;
  checked: boolean;
  disabled: boolean;
  loading: boolean;
  onChange: (value: boolean) => void;
}) {
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        gap: 16,
        alignItems: "flex-start",
      }}
    >
      <div>
        <label htmlFor={id}>{label}</label>
        <div className="pf-hint">{hint}</div>
      </div>
      <Switch id={id} checked={checked} disabled={disabled} loading={loading} onChange={onChange} />
    </div>
  );
}

/**
 * Профиль → «Уведомления» (W13-A6): личные сообщения бота в Telegram — подписки и «Тестовое уведомление». Доступно каждому
 * вошедшему сотруднику (BFF `/me/notification-settings`, `/me/test-notification`); системные оповещения предлагаются тем,
 * у кого есть раздел Admin. Telegram привязывает администратор в карточке сотрудника.
 */
export function NotificationSettings({ me }: { me: Me }) {
  const { t } = useTranslation("audit");
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const format = useFormat();
  const base = useId();
  const settings = useGetNotificationSettings();
  const update = useUpdateNotificationSettings({
    mutation: {
      onSuccess: (next) => {
        queryClient.setQueryData(getGetNotificationSettingsQueryKey(), next);
        void message.success(t("profile.saved"));
      },
    },
  });
  const test = useSendTestNotification({
    mutation: {
      onSuccess: () => {
        void message.success(t("profile.testSent"));
        void queryClient.invalidateQueries({ queryKey: getGetNotificationSettingsQueryKey() });
      },
    },
  });

  let body;
  if (settings.isPending) {
    body = <Skeleton active paragraph={{ rows: 3 }} title={false} />;
  } else if (settings.isError) {
    body = (
      <Alert
        type="error"
        showIcon
        message={t("profile.loadError")}
        action={
          <Button
            size="small"
            onClick={() => {
              void settings.refetch();
            }}
          >
            {t("profile.retry")}
          </Button>
        }
      />
    );
  } else {
    const data = settings.data;
    const linked = data.telegram_linked;
    const errorKey = test.isError ? testErrorKey(test.error) : null;
    body = (
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <div>
          <strong>{t("profile.telegram")}: </strong>
          <span>{linked ? t("profile.linked") : t("profile.notLinked")}</span>
        </div>
        {!linked ? <Alert type="info" showIcon message={t("profile.linkHint")} /> : null}
        {linked && data.delivery_failed_at ? (
          <Alert
            type="warning"
            showIcon
            message={t("profile.failed", {
              time: format.date(data.delivery_failed_at, "datetime"),
            })}
          />
        ) : null}
        <Row
          id={`${base}-leads`}
          label={t("profile.leads")}
          hint={t("profile.leadsHint")}
          checked={data.notify_leads}
          disabled={!linked}
          loading={update.isPending}
          onChange={(value) => {
            update.mutate({ data: { notify_leads: value } });
          }}
        />
        {canSee(me, { resource: "admin" }) ? (
          <Row
            id={`${base}-system`}
            label={t("profile.system")}
            hint={t("profile.systemHint")}
            checked={data.notify_system}
            disabled={!linked}
            loading={update.isPending}
            onChange={(value) => {
              update.mutate({ data: { notify_system: value } });
            }}
          />
        ) : null}
        <div>
          <Button
            loading={test.isPending}
            disabled={!linked}
            onClick={() => {
              test.mutate();
            }}
          >
            {t("profile.test")}
          </Button>
          <div className="pf-hint">{t("profile.testHint")}</div>
        </div>
        {errorKey ? (
          <Alert type="error" showIcon role="alert" message={t(`profile.errors.${errorKey}`)} />
        ) : null}
      </div>
    );
  }

  return (
    <section aria-labelledby={`${base}-title`} style={{ marginTop: 16 }}>
      <h3
        id={`${base}-title`}
        style={{ margin: "0 0 4px", fontSize: 16, lineHeight: "24px", fontWeight: 600 }}
      >
        {t("profile.notifications")}
      </h3>
      <p className="pf-hint" style={{ margin: "0 0 12px" }}>
        {t("profile.intro")}
      </p>
      {body}
    </section>
  );
}
