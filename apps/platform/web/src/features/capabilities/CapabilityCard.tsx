import { Alert, Button, Skeleton } from "antd";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { useGetEmployeeCapabilities } from "../../shared/api/generated/platform-bff";
import type { EmployeeCapabilities } from "../../shared/api/generated/model";
import { SummaryBox } from "./SummaryBox";

import "./capabilities.css";

/**
 * «Что может этот человек» в боковом окне списка (ДОСТ-1п): только короткий итог по областям и ссылка «Открыть» на страницу
 * человека (там таблица, «Отвечает за», «Подписывает», «Замещение»); плюс честная ссылка на выдачу прав ролями.
 */
export function CapabilityCard({
  employeeId,
  rolesTargetId,
}: {
  employeeId: string;
  /** `id` блока выдачи ролей на этой же карточке; без него ссылки нет (нет права выдавать) */
  rolesTargetId?: string;
}) {
  const { t } = useTranslation("capabilities");
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
      <h3 id="pf-cap-card-title" style={{ margin: "0 0 8px", fontSize: 16, fontWeight: 600 }}>
        {t("card.heading")}
      </h3>
      <SummaryBox data={data} person="third" compact />
      <p style={{ margin: "8px 0 0" }}>
        <Link to={`/admin/org/${employeeId}`} data-testid="cap-open-page">
          {t("card.open")}
        </Link>
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
