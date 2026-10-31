import { Alert, App, Button, Card, Skeleton } from "antd";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router";

import { useViewport } from "../../../app/shell/useViewport";
import { ApiError } from "../../../shared/api/errors";
import type { CalcSheet } from "../../../shared/api/generated/model";
import {
  useGetCalcSheet,
  useMarkCalcReady,
  useStartCalc,
} from "../../../shared/api/generated/platform-bff";
import { useDocumentTitle } from "../../../shared/lib/useDocumentTitle";
import { useFormat } from "../../../shared/lib/useFormat";
import { Consequence } from "../../../shared/ui/Consequence";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { QueryState } from "../../../shared/ui/FormParts";
import { LinkButton } from "../../../shared/ui/LinkButton";
import { PageHeader } from "../../../shared/ui/PageHeader";
import { RequestSteps } from "../../../shared/ui/RequestSteps";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { AddLineModal } from "./AddLineModal";
import { calcRef, readyHintKey, useApplySheet, useErrorText, useStateLabels } from "./api";
import { LinesTable } from "./LinesTable";
import { ParseModal } from "./ParseModal";
import { PriceRequestModal } from "./PriceRequestModal";
import { PriceRequests } from "./PriceRequests";
import { TaskSlot } from "./TaskPanel";

import "./calc.css";

const GROUPS = ["stock", "supply", "engineer"] as const;

function stateOf(sheet: CalcSheet) {
  return sheet.quote ? sheet.quote.state : "not_started";
}

function Banner({ sheet }: { sheet: CalcSheet }) {
  const { t } = useTranslation("calc");
  const quote = sheet.quote;
  if (!quote) return null;
  if (quote.state === "at_director") {
    return (
      <Alert type="info" showIcon message={t("sheet.atDirector", { number: quote.number ?? "" })} />
    );
  }
  if (quote.state === "returned") {
    return (
      <Alert
        type="warning"
        showIcon
        message={t("sheet.returned", { comment: quote.director_comment ?? "" })}
      />
    );
  }
  if (quote.state === "rejected")
    return <Alert type="error" showIcon message={t("sheet.rejected")} />;
  if (quote.state === "approved")
    return <Alert type="success" showIcon message={t("sheet.approved")} />;
  if (!sheet.rights.goods && !sheet.rights.services) {
    return <Alert type="info" showIcon message={t("sheet.readOnly")} />;
  }
  return null;
}

function NotStarted({ sheet }: { sheet: CalcSheet }) {
  const { t } = useTranslation("calc");
  const { message } = App.useApp();
  const apply = useApplySheet();
  const errorText = useErrorText();
  const start = useStartCalc({
    mutation: {
      onSuccess: apply,
      onError: (error) => {
        void message.error(errorText(error));
      },
    },
  });
  const consequence = t("sheet.notStarted.consequence", { returnObjects: true }) as string[];
  return (
    <Card size="small" title={<h2 className="pf-calc-title">{t("sheet.notStarted.title")}</h2>}>
      <div className="pf-calc-stack">
        <p>
          {sheet.request.lines
            ? t("sheet.notStarted.textLines", { count: sheet.request.lines })
            : t("sheet.notStarted.textEmpty")}
        </p>
        <div>
          <h3 className="pf-calc-subtitle">{t("sheet.request")}</h3>
          <p className="pf-calc-request">{sheet.request.text || t("sheet.requestEmpty")}</p>
        </div>
        {sheet.rights.build ? (
          <>
            <div>
              <Button
                type="primary"
                loading={start.isPending}
                onClick={() => {
                  start.mutate({ number: calcRef(sheet.number) });
                }}
              >
                {t("sheet.notStarted.action")}
              </Button>
            </div>
            <Consequence items={consequence} />
          </>
        ) : (
          <p className="pf-hint">{t("sheet.notStarted.noRights")}</p>
        )}
      </div>
    </Card>
  );
}

function Ready({ sheet }: { sheet: CalcSheet }) {
  const { t } = useTranslation("calc");
  const { message } = App.useApp();
  const apply = useApplySheet();
  const errorText = useErrorText();
  const hintId = useId();
  const ready = useMarkCalcReady({
    mutation: {
      onSuccess: (next) => {
        apply(next);
        void message.success(t("ready.done"));
      },
      onError: (error) => {
        void message.error(errorText(error));
      },
    },
  });
  if (stateOf(sheet) === "at_director") {
    return (
      <div className="pf-calc-ready">
        <StatusTag kind="quote" status="at_director">
          {t("ready.done")}
        </StatusTag>
      </div>
    );
  }
  if (!sheet.rights.build) return null;
  const blocker = sheet.ready.blocker;
  const waiting = GROUPS.filter((g) => sheet.visas[g].state === "waiting").map((g) =>
    t(`groups.${g}`),
  );
  const consequence = t("ready.consequence", { returnObjects: true }) as string[];
  return (
    <div className="pf-calc-ready">
      {blocker ? (
        <p id={hintId} className="pf-calc-ready-hint">
          {t(`ready.hint.${readyHintKey(sheet)}`, { count: sheet.ready.missing })}
          {blocker === "visas_missing" && waiting.length
            ? ` ${t("ready.missingGroups", { groups: waiting.join(", ") })}`
            : ""}
        </p>
      ) : null}
      <div>
        <Button
          type="primary"
          disabled={!sheet.ready.allowed}
          loading={ready.isPending}
          aria-describedby={blocker ? hintId : undefined}
          onClick={() => {
            ready.mutate({ number: calcRef(sheet.number) });
          }}
        >
          {t("ready.button")}
        </Button>
      </div>
      <Consequence items={consequence} />
    </div>
  );
}

function Content({ sheet }: { sheet: CalcSheet }) {
  const { t } = useTranslation(["calc"]);
  const { date } = useFormat();
  const { mobile } = useViewport();
  const [, setParams] = useSearchParams();
  const [dialog, setDialog] = useState<"add" | "parse" | "price" | null>(null);
  const state = stateOf(sheet);
  const editable = state === "in_progress" || state === "returned";
  const canLines = sheet.rights.goods || sheet.rights.services;
  const subtitle = [
    t("sheet.subtitle", {
      client: sheet.client ?? sheet.title,
      letter: sheet.task.letter_number,
      due: date(sheet.task.due),
    }),
    sheet.task.min_margin_pct ? t("sheet.margin", { value: sheet.task.min_margin_pct }) : null,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <div className="pf-calc">
      <PageHeader
        title={t("sheet.title", { number: sheet.number })}
        subtitle={subtitle}
        extra={
          <div className="pf-calc-row">
            <StatusTag kind="quote" status={state}>
              {t(`state.${state}`)}
            </StatusTag>
            {sheet.quote !== null && sheet.rights.stock === true ? (
              <Button
                onClick={() => {
                  setDialog("price");
                }}
              >
                {t("sheet.requestPrice")}
              </Button>
            ) : null}
            {mobile ? (
              <Button
                onClick={() => {
                  setParams(
                    (prev) => {
                      const next = new URLSearchParams(prev);
                      next.set("panel", "open");
                      next.set("tab", "task");
                      return next;
                    },
                    { replace: true },
                  );
                }}
              >
                {t("sheet.openTask")}
              </Button>
            ) : null}
          </div>
        }
      />
      <section className="pf-card pf-calc-steps" aria-label={t("sheet.steps")}>
        <RequestSteps stage={sheet.step} number={sheet.number} />
      </section>
      <Banner sheet={sheet} />
      {sheet.quote === null ? (
        <NotStarted sheet={sheet} />
      ) : (
        <Card
          size="small"
          title={<h2 className="pf-calc-title">{t("lines.title")}</h2>}
          extra={
            editable && canLines ? (
              <div className="pf-calc-row">
                <Button
                  onClick={() => {
                    setDialog("add");
                  }}
                >
                  {t("add.button")}
                </Button>
                {sheet.rights.build ? (
                  <Button
                    onClick={() => {
                      setDialog("parse");
                    }}
                  >
                    {t("parse.button")}
                  </Button>
                ) : null}
              </div>
            ) : null
          }
          styles={{ body: { padding: 0 } }}
        >
          <LinesTable sheet={sheet} />
          <Ready sheet={sheet} />
        </Card>
      )}
      {sheet.quote !== null ? <PriceRequests sheet={sheet} /> : null}
      {dialog === "price" ? (
        <PriceRequestModal
          sheet={sheet}
          onClose={() => {
            setDialog(null);
          }}
        />
      ) : null}
      {dialog === "add" ? (
        <AddLineModal
          sheet={sheet}
          onClose={() => {
            setDialog(null);
          }}
        />
      ) : null}
      {dialog === "parse" ? (
        <ParseModal
          sheet={sheet}
          onClose={() => {
            setDialog(null);
          }}
        />
      ) : null}
      <TaskSlot number={sheet.number} />
    </div>
  );
}

/**
 * Расчёт · «Расчёт по заявке ЗВ-…» (SPEC-v3 §7.4, путь заявки шаг 3): шкала, задание из резолюции, строки на всю ширину
 * (склад, поставщик и срок, закупка и цена клиенту, наценка, виза по зоне), итоги без НДС, «Расчёт готов → черновик КП
 * директору» (неактивна, пока есть строки без визы, — с подписью почему). Боковое окно — «Задание».
 */
export function CalcScreen({ number }: { number: string }) {
  const { t } = useTranslation("calc");
  const query = useGetCalcSheet(calcRef(number));
  const labels = useStateLabels();
  useDocumentTitle(t("sheet.title", { number }));

  const error = query.error;
  if (error instanceof ApiError && error.status === 404) {
    return (
      <EmptyState
        title={t("load.notFound.title")}
        text={t("load.notFound.text")}
        action={<LinkButton to="/erp/requests">{t("load.notFound.action")}</LinkButton>}
      />
    );
  }
  if (query.isPending) {
    return (
      <div className="pf-calc">
        <Skeleton active paragraph={{ rows: 8 }} />
      </div>
    );
  }
  return (
    <QueryState query={query} labels={labels}>
      {(sheet) => <Content sheet={sheet} />}
    </QueryState>
  );
}
