import { App as AntApp } from "antd";
import { useState, type ReactNode } from "react";

import { useServiceSwitch } from "../../api/externalServiceQueries";
import type { ExternalServiceOut } from "../../api/generated/model";
import { useApiErrorToast } from "../../hooks/useApiErrorToast";
import { t } from "../../i18n/ru";
import { SwitchDialog } from "./SwitchDialog";

type Target = { service: ExternalServiceOut; disabling: boolean };

/** Окно выключателя для списка и деталки: открыть → пароль → запрос → тост → обновление. */
export function useSwitchFlow(): {
  open: (service: ExternalServiceOut) => void;
  dialog: ReactNode;
} {
  const { message } = AntApp.useApp();
  const onError = useApiErrorToast();
  const [target, setTarget] = useState<Target | null>(null);
  const { disable, enable } = useServiceSwitch(onError, () => {
    void message.success(
      target?.disabling
        ? t.externalServices.switch.disabledDone
        : t.externalServices.switch.enabledDone,
    );
    setTarget(null);
  });
  const dialog = target ? (
    <SwitchDialog
      service={target.service}
      disabling={target.disabling}
      saving={disable.isPending || enable.isPending}
      onCancel={() => {
        setTarget(null);
      }}
      onSubmit={(password, reason) => {
        const key = target.service.key;
        if (target.disabling) disable.mutate({ key, data: { password, reason } });
        else enable.mutate({ key, data: { password } });
      }}
    />
  ) : null;
  return {
    open: (service) => {
      setTarget({ service, disabling: !service.switch?.disabled });
    },
    dialog,
  };
}
