import { Input } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { ExternalService } from "../../../shared/api/generated/model";
import {
  useDisableExternalService,
  useEnableExternalService,
} from "../../../shared/api/generated/platform-bff";
import { ActionForm, Field } from "./parts";
import { useRefreshIntegrations } from "./refresh";

/** Выключатель сервиса: «Что произойдёт», пароль администратора, причина в журнал. */
export function SwitchForm({ service, onDone }: { service: ExternalService; onDone: () => void }) {
  const { t } = useTranslation("integrations");
  const refresh = useRefreshIntegrations();
  const [reason, setReason] = useState("");
  const disabled = service.switch?.disabled ?? false;
  const onSuccess = () => {
    refresh();
    onDone();
  };
  const disable = useDisableExternalService({ mutation: { onSuccess } });
  const enable = useEnableExternalService({ mutation: { onSuccess } });
  const active = disabled ? enable : disable;
  const effect = service.switch?.effect;
  return (
    <ActionForm
      id={`svc-${service.key}`}
      title={t(disabled ? "services.enable.title" : "services.disable.title", {
        title: service.title,
      })}
      submitLabel={t(disabled ? "services.enable.submit" : "services.disable.submit")}
      danger={!disabled}
      pending={active.isPending}
      error={active.error}
      consequence={
        disabled
          ? [t("services.enable.step1"), t("services.enable.step2")]
          : [
              effect ?? t("services.disable.step1"),
              t("services.disable.step2"),
              t("services.disable.step3"),
            ]
      }
      onCancel={onDone}
      onSubmit={(password) => {
        if (disabled) enable.mutate({ key: service.key, data: { password } });
        else
          disable.mutate({
            key: service.key,
            data: { password, ...(reason.trim() ? { reason: reason.trim() } : {}) },
          });
      }}
    >
      {disabled ? null : (
        <Field id={`svc-${service.key}-reason`} label={t("services.disable.reason")}>
          <Input
            id={`svc-${service.key}-reason`}
            value={reason}
            maxLength={200}
            autoComplete="off"
            onChange={(event) => {
              setReason(event.target.value);
            }}
          />
        </Field>
      )}
    </ActionForm>
  );
}
