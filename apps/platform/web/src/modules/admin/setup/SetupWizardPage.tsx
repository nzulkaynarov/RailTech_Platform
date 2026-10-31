import { useQueryClient } from "@tanstack/react-query";
import { Alert, App, Button, Card, Skeleton } from "antd";
import { type ReactNode, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useSearchParams } from "react-router";

import { canEdit } from "../../../app/access";
import { useAuth } from "../../../app/auth/useAuth";
import { resetBannerHidden, useBannerHidden } from "../../../features/first-run/hidden";
import { useSetupChecklist } from "../../../features/first-run/useSetupChecklist";
import { PanelPortal } from "../../../app/shell/PanelSlot";
import { ERP_RECHECK } from "../../../entities/setup/recheck";
import {
  STEP_TARGET,
  WIZARD_PATH,
  isStepKey,
  staysOnCompany,
  stepAfter,
} from "../../../entities/setup/steps";
import type { SetupChecklist, SetupStepKey } from "../../../shared/api/generated/model";
import { useDocumentTitle } from "../../../shared/lib/useDocumentTitle";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { PageHeader } from "../../../shared/ui/PageHeader";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { CompanyStep } from "./CompanyStep";
import { ConnectionsStep } from "./ConnectionsStep";
import { ErpStep } from "./ErpStep";
import { StepPanel } from "./StepPanel";

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
 * первый сотрудник). Состояние приносит BFF; сделать шаг можно позже. W15-H4: форма шага открывается в боковом окне
 * мастера (`?step=`), после сохранения — следующий шаг; баннер, скрытый до завтра, возвращается кнопкой здесь.
 * Только администратор: директору чек-лист не отдаётся (BFF — 403).
 */
export function SetupWizardPage() {
  const { t } = useTranslation("modules");
  const { message } = App.useApp();
  const { me } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const editable = canEdit(me, "admin");
  const title = t("admin.setup.title");
  useDocumentTitle(title);
  const checklist = useSetupChecklist(editable, { fresh: true });
  const bannerHidden = useBannerHidden(me.id);
  const stepParam = params.get("step");
  const step = editable && isStepKey(stepParam) ? stepParam : null;

  // Форма шага сохранила (мутация в окне завершилась успешно) — перечитать чек-лист: шаг мог стать «Готово». Событие кэша
  // мутаций, а не счётчик `useIsMutating`: быстрый ответ проходит 1 → 0 между двумя отрисовками, и переход терялся.
  const queryClient = useQueryClient();
  const { refetch } = checklist;
  useEffect(() => {
    if (!step) return;
    return queryClient.getMutationCache().subscribe((event) => {
      if (event.type === "updated" && event.action.type === "success") void refetch();
    });
  }, [queryClient, step, refetch]);

  const goNext = (data: SetupChecklist, current: SetupStepKey) => {
    // ERP готова, а своей компании ещё нет (или ERP ещё не выдала доступ и данных о компании нет — W15-G-10):
    // следующий шаг — компания прямо в мастере, а не «Telegram-бот».
    if (current === "erp" && staysOnCompany(data)) {
      void navigate(`${WIZARD_PATH}?panel=closed`, { replace: true });
      return;
    }
    const after = stepAfter(data, current);
    if (after) void navigate(STEP_TARGET[after.key], { replace: true });
    else void navigate(`${WIZARD_PATH}?panel=closed`, { replace: true });
  };

  // После «Сохранить» — сразу следующий шаг (UX-оценка §5 P1-6): шаг стал «Готово», пока его окно открыто. Первого
  // сотрудника не переключаем сами: временный пароль показывается один раз, его надо успеть переписать.
  const openedAs = useRef<{ step: SetupStepKey; done: boolean } | null>(null);
  const data = checklist.data;
  useEffect(() => {
    if (!step || !data) {
      openedAs.current = null;
      return;
    }
    const done = data.steps.find((s) => s.key === step)?.state === "done";
    if (openedAs.current?.step !== step) {
      openedAs.current = { step, done };
      return;
    }
    if (!openedAs.current.done && done && step !== "first_employee") {
      openedAs.current = { step, done };
      void message.success(
        t("admin.setup.stepSaved", { step: t(`admin.setup.steps.${step}.title`) }),
      );
      goNext(data, step);
    }
    // goNext и message стабильны по смыслу; перезапуск — только при смене шага или состояния
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step, data]);

  // ERP сопряжена, но доступа к данным компании ещё нет: мастер сам перепроверяет несколько раз (W15-G-10).
  const waitingErp =
    editable && data?.company === null && data.company_blocker === "erp_unavailable";
  const [rechecks, setRechecks] = useState(0);
  useEffect(() => {
    if (!waitingErp || rechecks >= ERP_RECHECK.attempts) return;
    const timer = window.setTimeout(() => {
      setRechecks((n) => n + 1);
      void refetch();
    }, ERP_RECHECK.everyMs);
    return () => {
      window.clearTimeout(timer);
    };
  }, [waitingErp, rechecks, refetch]);
  const rechecking = waitingErp && rechecks < ERP_RECHECK.attempts;

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
          status={
            <StatusTag kind="setupStep" status="done">
              {t("admin.setup.state.done")}
            </StatusTag>
          }
        >
          <p style={{ margin: 0 }}>{t("admin.setup.adminDone", { name: me.name })}</p>
        </StepCard>
        <StepCard
          title={t("admin.setup.erpTitle")}
          status={
            <StatusTag kind="setupStep" status={erpStep?.state ?? "unknown"}>
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
              <StatusTag kind="setupStep" status="unknown">
                {t(
                  data.company_blocker === "erp_not_connected"
                    ? "admin.setup.state.waitingErp"
                    : "admin.setup.state.unknown",
                )}
              </StatusTag>
            ) : (
              <StatusTag kind="setupStep" status={data.company.required ? "todo" : "done"}>
                {t(data.company.required ? "admin.setup.state.todo" : "admin.setup.state.done")}
              </StatusTag>
            )
          }
        >
          <CompanyStep
            company={data.company}
            blocker={data.company_blocker}
            retrying={checklist.isFetching}
            waiting={rechecking}
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

  const stepState = step ? data?.steps.find((s) => s.key === step)?.state : undefined;
  const after = step && data ? stepAfter(data, step) : undefined;
  const closePanel = () => {
    void navigate(`${WIZARD_PATH}?panel=closed`, { replace: true });
  };

  return (
    <>
      <PageHeader title={title} subtitle={t("admin.setup.subtitle")} />
      {editable && bannerHidden ? (
        <Alert
          type="info"
          showIcon
          message={t("admin.setup.bannerHidden")}
          action={
            <Button
              size="small"
              onClick={() => {
                resetBannerHidden(me.id);
              }}
            >
              {t("admin.setup.bannerReturn")}
            </Button>
          }
        />
      ) : null}
      {body}
      {step && data && stepState ? (
        <PanelPortal tab="step">
          <StepPanel
            key={step}
            step={step}
            state={stepState}
            next={after ? t(`admin.setup.steps.${after.key}.title`) : null}
            onNext={() => {
              goNext(data, step);
            }}
            onClose={closePanel}
            onInvited={() => {
              void refetch().then((result) => {
                if (result.data) goNext(result.data, step);
              });
            }}
          />
        </PanelPortal>
      ) : null}
    </>
  );
}
