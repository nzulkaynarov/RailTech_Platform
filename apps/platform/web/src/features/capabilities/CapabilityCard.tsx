import { Alert, Button, Skeleton } from "antd";
import { useTranslation } from "react-i18next";

import { useGetEmployeeCapabilities } from "../../shared/api/generated/platform-bff";
import type { EmployeeCapabilities } from "../../shared/api/generated/model";
import { CapabilityRows } from "./CapabilityRows";
import { DeputyBlock, SigningBlock, ZonesBlock } from "./PersonBlocks";
import { pickText } from "./model";

import "./capabilities.css";

/**
 * «Что может этот человек» в карточке сотрудника (ДОСТ-1, только чтение): итог словами, строки возможностей по шагам
 * сделки, «Отвечает за», «Подписывает», «Замещение» и честная ссылка на выдачу прав ролями — выдача пока та же.
 */
export function CapabilityCard({
  employeeId,
  rolesTargetId,
}: {
  employeeId: string;
  /** `id` блока выдачи ролей на этой же карточке; без него ссылки нет (нет права выдавать) */
  rolesTargetId?: string;
}) {
  const { t, i18n } = useTranslation("capabilities");
  const query = useGetEmployeeCapabilities(employeeId);
  if (query.isPending) return <Skeleton active paragraph={{ rows: 6 }} />;
  if (query.isError) {
    return (
      <Alert
        type="error"
        showIcon
        message={t("card.unavailable")}
        action={
          <Button
            size="small"
            onClick={() => {
              void query.refetch();
            }}
          >
            {t("card.retry")}
          </Button>
        }
      />
    );
  }
  const data: EmployeeCapabilities = query.data;
  return (
    <section className="pf-cap-card" aria-labelledby="pf-cap-card-title" data-testid="cap-card">
      <h3 id="pf-cap-card-title" style={{ margin: "0 0 4px", fontSize: 16, fontWeight: 600 }}>
        {t("card.heading")}
      </h3>
      <p className="pf-hint" style={{ margin: "0 0 12px" }}>
        {t("card.positionNote")}
      </p>
      <CapabilityRows data={data} showOthers />
      <ZonesBlock title={t("card.responsibleTitle")} known={data.zones_known} items={data.zones} />
      <SigningBlock
        title={t("card.signingTitle")}
        known={data.signing_known}
        items={data.signing}
      />
      <DeputyBlock
        title={t("card.deputyTitle")}
        deputy={data.deputy}
        noneText={t("card.deputyNone")}
      />
      <p className="pf-hint" style={{ marginTop: 16 }}>
        {t("card.free", { text: pickText(data.free_for_all, i18n.language) })}
      </p>
      {rolesTargetId ? (
        <p style={{ margin: "12px 0 0" }}>
          <Button
            type="link"
            style={{ padding: 0, height: "auto" }}
            data-testid="cap-change-link"
            onClick={() => {
              const target = document.getElementById(rolesTargetId);
              target?.scrollIntoView({ block: "start" });
              target?.focus();
            }}
          >
            {t("card.change")}
          </Button>
          <span className="pf-hint" style={{ display: "block" }}>
            {t("card.changeHint")}
          </span>
        </p>
      ) : null}
    </section>
  );
}
