import { Alert, Button, Skeleton } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { WriteToAdminModal } from "../tickets/WriteToAdminModal";
import { useGetMyCapabilities } from "../../shared/api/generated/platform-bff";
import { CapabilityRows } from "./CapabilityRows";
import { DeputyBlock, SigningBlock, ZonesBlock } from "./PersonBlocks";
import { pickText } from "./model";

import "./capabilities.css";

/**
 * «Мои возможности» в профиле (ДОСТ-1): те же данные, что в карточке человека у администратора, про самого сотрудника — только
 * чтение. Нужна другая возможность — «Попросить возможность» (обращение администратору, то же окно, что «Нет доступа»).
 */
export function MyCapabilities() {
  const { t, i18n } = useTranslation("capabilities");
  const query = useGetMyCapabilities();
  const [asking, setAsking] = useState(false);
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
  const data = query.data;
  return (
    <div data-testid="my-capabilities">
      <p className="pf-hint" style={{ margin: "0 0 12px" }}>
        {t("mine.lead")}
      </p>
      <CapabilityRows data={data} />
      <ZonesBlock title={t("mine.responsibleTitle")} known={data.zones_known} items={data.zones} />
      <SigningBlock
        title={t("mine.signingTitle")}
        known={data.signing_known}
        items={data.signing}
      />
      <DeputyBlock
        title={t("mine.deputyTitle")}
        deputy={data.deputy}
        noneText={t("mine.deputyNone")}
      />
      <p className="pf-hint" style={{ marginTop: 16 }}>
        {t("card.free", { text: pickText(data.free_for_all, i18n.language) })}
      </p>
      <p style={{ display: "flex", gap: 12, flexWrap: "wrap", margin: "16px 0 0" }}>
        <Button
          onClick={() => {
            setAsking(true);
          }}
        >
          {t("mine.ask")}
        </Button>
        <Link to="/dashboard/queue">{t("mine.openTasks")}</Link>
      </p>
      {asking ? (
        <WriteToAdminModal
          open
          defaultSubject="access"
          onClose={() => {
            setAsking(false);
          }}
        />
      ) : null}
    </div>
  );
}
