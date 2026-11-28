import { Alert, Button, Skeleton } from "antd";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { useGetEmployeeCapabilities } from "../../shared/api/generated/platform-bff";
import type { EmployeeCapabilities } from "../../shared/api/generated/model";
import { SummaryBox } from "./SummaryBox";

import "./capabilities.css";

/**
 * «Что может этот человек» в боковом окне списка (ДОСТ-1п): только короткий итог по областям и ссылка «Открыть» на страницу
 * человека (там таблица, «Отвечает за», «Подписывает», «Замещение»);.
 */
export function CapabilityCard({ employeeId }: { employeeId: string }) {
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
    </section>
  );
}
