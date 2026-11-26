import { useQueryClient } from "@tanstack/react-query";
import { Alert, Button, Skeleton, Switch } from "antd";
import { useId, useState } from "react";
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
import {
  browserPermission,
  requestBrowserPermission,
  type BrowserPermission,
} from "../../shared/notify/browserNotify";
import { useNotify } from "../../shared/notify/NotifyProvider";
import { useNotifyPrefs } from "../../shared/notify/prefs";
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
 * у кого есть раздел Admin. Заголовок блока даёт страница `/me`; Telegram сотрудник привязывает там же, выше (W15-H6).
 */
export function NotificationSettings({ me }: { me: Me }) {
  const { t } = useTranslation("audit");
  const notify = useNotify();
  const [prefs, setPrefs] = useNotifyPrefs(me.id);
  const [permission, setPermission] = useState<BrowserPermission>(browserPermission);
  const queryClient = useQueryClient();
  const format = useFormat();
  const base = useId();
  const settings = useGetNotificationSettings();
  const update = useUpdateNotificationSettings({
    mutation: {
      onSuccess: (next) => {
        queryClient.setQueryData(getGetNotificationSettingsQueryKey(), next);
        notify.success(t("profile.saved"));
      },
    },
  });
  const test = useSendTestNotification({
    mutation: {
      onSuccess: () => {
        notify.success(t("profile.testSent"));
        void queryClient.invalidateQueries({ queryKey: getGetNotificationSettingsQueryKey() });
      },
    },
  });

  const turnBrowser = async (value: boolean) => {
    if (!value) {
      setPrefs({ browser: false });
      return;
    }
    // разрешение просим только по этому щелчку, не при загрузке страницы
    const result = await requestBrowserPermission();
    setPermission(result);
    setPrefs({ browser: result === "granted" });
  };
  const local = (
    <div style={{ display: "flex", flexDirection: "column", gap: 12, marginBottom: 16 }}>
      <Row
        id={`${base}-popups`}
        label={t("profile.popups")}
        hint={t("profile.popupsHint")}
        checked={prefs.popups}
        disabled={false}
        loading={false}
        onChange={(value) => {
          setPrefs({ popups: value });
        }}
      />
      <Row
        id={`${base}-popups-only`}
        label={t("profile.popupsOnly")}
        hint={t("profile.popupsOnlyHint")}
        checked={prefs.onlyAction}
        disabled={!prefs.popups}
        loading={false}
        onChange={(value) => {
          setPrefs({ onlyAction: value });
        }}
      />
      <Row
        id={`${base}-browser`}
        label={t("profile.browser")}
        hint={t("profile.browserHint")}
        checked={prefs.browser && permission === "granted"}
        disabled={permission === "unsupported" || permission === "denied"}
        loading={false}
        onChange={(value) => {
          void turnBrowser(value);
        }}
      />
      {permission === "denied" ? <div className="pf-hint">{t("profile.browserDenied")}</div> : null}
      {permission === "unsupported" ? (
        <div className="pf-hint">{t("profile.browserUnsupported")}</div>
      ) : null}
    </div>
  );

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
        <Row
          id={`${base}-decisions`}
          label={t("profile.decisions")}
          hint={t("profile.decisionsHint")}
          checked={data.notify_decisions ?? true}
          disabled={!linked}
          loading={update.isPending}
          onChange={(value) => {
            update.mutate({ data: { notify_decisions: value } });
          }}
        />
        <Row
          id={`${base}-tasks`}
          label={t("profile.tasks")}
          hint={t("profile.tasksHint")}
          checked={data.notify_tasks ?? false}
          disabled={!linked}
          loading={update.isPending}
          onChange={(value) => {
            update.mutate({ data: { notify_tasks: value } });
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
    <div>
      <p className="pf-hint" style={{ margin: "0 0 12px" }}>
        {t("profile.intro")}
      </p>
      {local}
      {body}
    </div>
  );
}
