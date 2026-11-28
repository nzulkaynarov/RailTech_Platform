import { Alert, Button, Skeleton } from "antd";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import type { EmployeeCapabilities } from "../../shared/api/generated/model";
import {
  useGetEmployeeCapabilities,
  useListEmployees,
} from "../../shared/api/generated/platform-bff";
import { useCrumbTitle } from "../../shared/lib/crumbTitle";
import { useDocumentTitle } from "../../shared/lib/useDocumentTitle";
import { EmployeeStatusTag } from "../../modules/admin/org/EmployeeCells";
import { PersonAvatar } from "../../shared/ui/EntityCell";
import { PageFrame } from "../../shared/ui/PageFrame";
import { CapabilityRows } from "./CapabilityRows";
import { DeputyBlock, SigningBlock, ZonesBlock } from "./PersonBlocks";
import { SummaryBox } from "./SummaryBox";
import { pickText } from "./model";

import "./capabilities.css";

const TABLE_ID = "pf-cap-table";
const openTable = () => {
  document.getElementById(TABLE_ID)?.scrollIntoView({ block: "start" });
};

/**
 * Страница человека (ДОСТ-1п): слева таблица возможностей по областям с раскрытием в действия, справа «Отвечает за»,
 * «Подписывает», «Замещение»; сверху короткий итог словами. Только чтение; роли выдаются в карточке сотрудника.
 */
export function EmployeeCapabilitiesPage({ id }: { id: string }) {
  const { t, i18n } = useTranslation("capabilities");
  const query = useGetEmployeeCapabilities(id);
  const staff = useListEmployees();
  const employee = staff.data?.items.find((item) => item.id === id);
  const name = query.data?.employee.name ?? employee?.name ?? "";
  useDocumentTitle(name || t("card.heading"));
  useCrumbTitle(name || null);

  let body;
  if (query.isPending) body = <Skeleton active paragraph={{ rows: 8 }} />;
  else if (query.isError) {
    body = (
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
  } else {
    const data: EmployeeCapabilities = query.data;
    body = (
      <>
        <section className="pf-cap-box" aria-label={t("card.heading")}>
          <SummaryBox data={data} person="third" onMore={openTable} />
        </section>
        <div className="pf-cap-cols">
          <section className="pf-cap-box" id={TABLE_ID} aria-label={t("card.rows")}>
            <CapabilityRows data={data} showOthers />
            <p className="pf-hint" style={{ margin: "12px 0 0" }}>
              {t("card.free", { text: pickText(data.free_for_all, i18n.language) })}
            </p>
          </section>
          <div className="pf-cap-side">
            <div className="pf-cap-box">
              <ZonesBlock
                title={t("card.responsibleTitle")}
                known={data.zones_known}
                items={data.zones}
              />
            </div>
            <div className="pf-cap-box">
              <SigningBlock
                title={t("card.signingTitle")}
                known={data.signing_known}
                items={data.signing}
              />
            </div>
            <div className="pf-cap-box">
              <DeputyBlock
                title={t("card.deputyTitle")}
                deputy={data.deputy}
                noneText={t("card.deputyNone")}
              />
            </div>
          </div>
        </div>
      </>
    );
  }

  return (
    <PageFrame layout="object">
      <div className="pf-cap-page" data-testid="cap-page">
        <Link to="/admin/org" className="pf-hint">
          ← {t("card.back")}
        </Link>
        <header className="pf-cap-head">
          <PersonAvatar name={name} photoUrl={employee?.avatar_url} size={48} />
          <div className="pf-cap-head-main">
            <h1>{name}</h1>
            <p className="pf-hint" style={{ margin: 0 }}>
              {employee?.position ? `${employee.position} · ` : ""}
              {t("card.positionNote")}
            </p>
          </div>
          {employee ? <EmployeeStatusTag status={employee.status} /> : null}
          <Link to={`/admin/org?employee=${id}&panel=open`}>{t("card.changeRoles")}</Link>
        </header>
        {body}
      </div>
    </PageFrame>
  );
}
