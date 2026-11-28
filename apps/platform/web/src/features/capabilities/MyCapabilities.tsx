import { Alert, Button, Skeleton } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { WriteToAdminModal } from "../tickets/WriteToAdminModal";
import { useGetMyCapabilities } from "../../shared/api/generated/platform-bff";
import { CapabilityRows } from "./CapabilityRows";
import { SummaryBox } from "./SummaryBox";
import { DeputyBlock, SigningBlock, ZonesBlock } from "./PersonBlocks";
import { pickText } from "./model";

import "./capabilities.css";

const openTable = () => {
  document.getElementById("pf-cap-table-mine")?.scrollIntoView({ block: "start" });
};

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
    <div data-testid="my-capabilities" className="pf-cap-page">
      <section className="pf-cap-box">
        <SummaryBox data={data} person="first" onMore={openTable} />
      </section>
      <div className="pf-cap-cols">
        <section className="pf-cap-box" id="pf-cap-table-mine">
          <CapabilityRows data={data} />
          <p className="pf-hint" style={{ margin: "12px 0 0" }}>
            {t("card.free", { text: pickText(data.free_for_all, i18n.language) })}
          </p>
        </section>
        <div className="pf-cap-side">
          <div className="pf-cap-box">
            <ZonesBlock
              title={t("mine.responsibleTitle")}
              known={data.zones_known}
              items={data.zones}
            />
          </div>
          <div className="pf-cap-box">
            <SigningBlock
              title={t("mine.signingTitle")}
              known={data.signing_known}
              items={data.signing}
            />
          </div>
          <div className="pf-cap-box">
            <DeputyBlock
              title={t("mine.deputyTitle")}
              deputy={data.deputy}
              noneText={t("mine.deputyNone")}
            />
          </div>
          <p style={{ display: "flex", gap: 12, flexWrap: "wrap", margin: 0 }}>
            <Button
              onClick={() => {
                setAsking(true);
              }}
            >
              {t("mine.ask")}
            </Button>
            <Link to="/dashboard/queue">{t("mine.openTasks")}</Link>
          </p>
        </div>
      </div>
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
