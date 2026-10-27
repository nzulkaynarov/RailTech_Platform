import { Alert } from "antd";
import { useTranslation } from "react-i18next";

import { STEP_TARGET } from "../../../entities/setup/steps";
import type { SetupStep } from "../../../shared/api/generated/model";
import { LinkButton } from "../../../shared/ui/LinkButton";

/**
 * Шаг «Подключение ERP» (W13C-F1, дефект гейта C2A-G-1): стоит перед шагом «Ваша компания», потому что компания
 * создаётся в ERP. Не сопряжена — главная кнопка «Подключить ERP» (на новой установке без кода сопряжения) ведёт на
 * карточку ERP; сопряжена — состояние словами и ссылка на проверку связи.
 */
export function ErpStep({ step }: { step: SetupStep | undefined }) {
  const { t } = useTranslation("modules");
  const state = step?.state ?? "unknown";
  return (
    <div className="pf-panel-stack">
      {state === "done" ? (
        <p style={{ margin: 0 }}>{t("admin.setup.erpDone")}</p>
      ) : state === "todo" ? (
        <p style={{ margin: 0 }}>{t("admin.setup.erpLead")}</p>
      ) : (
        <Alert type="warning" showIcon message={t("admin.setup.erpUnknown")} />
      )}
      <div>
        <LinkButton type={state === "todo" ? "primary" : "default"} to={STEP_TARGET.erp}>
          {t(state === "todo" ? "admin.setup.steps.erp.action" : "admin.setup.erpOpen")}
        </LinkButton>
      </div>
    </div>
  );
}
