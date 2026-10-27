import { Button, Card, Skeleton } from "antd";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { canEdit } from "../../../app/access";
import { useAuth } from "../../../app/auth/useAuth";
import { useSetupChecklist } from "../../../features/first-run/useSetupChecklist";
import { useDocumentTitle } from "../../../shared/lib/useDocumentTitle";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { PageHeader } from "../../../shared/ui/PageHeader";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { CompanyStep } from "./CompanyStep";
import { ConnectionsStep } from "./ConnectionsStep";
import { ErpStep } from "./ErpStep";

import "../../../features/first-run/first-run.css";

function StepCard({
  title,
  status,
  children,
}: {
  title: string;
  status?: ReactNode;
  children: ReactNode;
}) {
  return (
    <Card>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
        <h2 style={{ margin: 0, fontSize: 16, lineHeight: "24px", fontWeight: 600 }}>{title}</h2>
        {status}
      </div>
      {children}
    </Card>
  );
}

/**
 * Admin · «Первый запуск» (`/admin/setup`, SPEC-v3 §7.6, W13-A4, порядок — W13C-F1): администратор (уже создан на
 * экране до входа) -> подключение ERP -> своя компания (создаётся в ERP) -> остальные подключения (бот, почта, модели,
 * первый сотрудник). Состояние приносит BFF; сделать шаг можно позже,
 * страница остаётся и после «Скрыть» на баннере. Только администратор: директору чек-лист не отдаётся (BFF — 403).
 */
export function SetupWizardPage() {
  const { t } = useTranslation("modules");
  const { me } = useAuth();
  const editable = canEdit(me, "admin");
  const title = t("admin.setup.title");
  useDocumentTitle(title);
  const checklist = useSetupChecklist(editable, { fresh: true });

  let body: ReactNode;
  if (!editable) {
    body = (
      <Card>
        <EmptyState title={title} text={t("admin.setup.onlyAdmin")} />
      </Card>
    );
  } else if (checklist.isPending) {
    body = <Skeleton active paragraph={{ rows: 8 }} title={false} />;
  } else if (checklist.isError) {
    body = (
      <Card>
        <EmptyState
          title={t("admin.setup.loadError")}
          text={t("admin.setup.loadErrorText")}
          action={
            <Button
              onClick={() => {
                void checklist.refetch();
              }}
            >
              {t("admin.setup.retry")}
            </Button>
          }
        />
      </Card>
    );
  } else {
    const data = checklist.data;
    const erpStep = data.steps.find((s) => s.key === "erp");
    const otherSteps = data.steps.filter((s) => s.key !== "erp");
    body = (
      <div className="pf-setup-stack">
        <StepCard
          title={t("admin.setup.adminTitle")}
          status={<StatusTag tone="green">{t("admin.setup.state.done")}</StatusTag>}
        >
          <p style={{ margin: 0 }}>{t("admin.setup.adminDone", { name: me.name })}</p>
        </StepCard>
        <StepCard
          title={t("admin.setup.erpTitle")}
          status={
            <StatusTag
              tone={
                erpStep?.state === "done" ? "green" : erpStep?.state === "todo" ? "gold" : "default"
              }
            >
              {t(`admin.setup.state.${erpStep?.state ?? "unknown"}`)}
            </StatusTag>
          }
        >
          <ErpStep step={erpStep} />
        </StepCard>
        <StepCard
          title={t("admin.setup.companyTitle")}
          status={
            data.company === null ? (
              <StatusTag tone="default">
                {t(
                  data.company_blocker === "erp_not_connected"
                    ? "admin.setup.state.waitingErp"
                    : "admin.setup.state.unknown",
                )}
              </StatusTag>
            ) : (
              <StatusTag tone={data.company.required ? "gold" : "green"}>
                {t(data.company.required ? "admin.setup.state.todo" : "admin.setup.state.done")}
              </StatusTag>
            )
          }
        >
          <CompanyStep
            company={data.company}
            blocker={data.company_blocker}
            retrying={checklist.isFetching}
            onRetry={() => {
              void checklist.refetch();
            }}
          />
        </StepCard>
        <StepCard
          title={t("admin.setup.connectionsTitle")}
          status={
            <span className="pf-hint">
              {t("admin.setup.progress", { done: data.done, total: data.total })}
            </span>
          }
        >
          <p className="pf-hint" style={{ margin: "0 0 4px" }}>
            {data.steps.every((s) => s.state === "done")
              ? t("admin.setup.allDone")
              : t("admin.setup.connectionsLead")}
          </p>
          <ConnectionsStep steps={otherSteps} />
        </StepCard>
      </div>
    );
  }

  return (
    <>
      <PageHeader title={title} subtitle={t("admin.setup.subtitle")} />
      {body}
    </>
  );
}
