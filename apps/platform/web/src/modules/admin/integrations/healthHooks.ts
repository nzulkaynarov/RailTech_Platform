import { App } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { ServiceGroup } from "../../../shared/api/generated/model";
import { checkExternalService } from "../../../shared/api/generated/platform-bff";
import { useFormat } from "../../../shared/lib/useFormat";
import { useRefreshIntegrations } from "./refresh";

/** «Проверить снова»: сразу проверяет все сервисы причины; восстановилось — строка исчезает, нет — честно скажем. */
export function useRecheck(group: ServiceGroup) {
  const { t } = useTranslation("integrations");
  const { message } = App.useApp();
  const refresh = useRefreshIntegrations();
  const [running, setRunning] = useState(false);
  const [outcome, setOutcome] = useState<{ type: "info" | "error"; text: string } | null>(null);
  const run = async () => {
    setRunning(true);
    setOutcome(null);
    try {
      const results = await Promise.all(group.service_keys.map((key) => checkExternalService(key)));
      const healthy = results.every((result) => result.service.state === "ok");
      if (healthy) void message.success(t("health.recheck.fixed", { subject: group.headline }));
      else setOutcome({ type: "info", text: t("health.recheck.still") });
      refresh();
    } catch {
      setOutcome({ type: "error", text: t("health.recheck.error", { subject: group.headline }) });
    } finally {
      setRunning(false);
    }
  };
  return { running, outcome, run };
}

export function useSinceText(since: string | null): string {
  const { t } = useTranslation("integrations");
  const { date } = useFormat();
  return since ? t("health.since", { date: date(since, "datetime") }) : t("health.notChecked");
}
