import { Button, Card, Skeleton } from "antd";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router";

import { canEdit, canSee } from "../../../app/access";
import { useAuth } from "../../../app/auth/useAuth";
import { useViewport } from "../../../app/shell/useViewport";
import { ApiError } from "../../../shared/api/errors";
import type { ProjectCard, ProjectInvoice } from "../../../shared/api/generated/model";
import { useGetEdsProject } from "../../../shared/api/generated/platform-bff";
import { useDocumentTitle } from "../../../shared/lib/useDocumentTitle";
import { useFormat } from "../../../shared/lib/useFormat";
import { DefinitionList } from "../../../shared/ui/DefinitionList";
import { DocList, DocRow } from "../../../shared/ui/DocRow";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { QueryState } from "../../../shared/ui/FormParts";
import { LinkButton } from "../../../shared/ui/LinkButton";
import { MoneyText } from "../../../shared/ui/MoneyText";
import { PageHeader } from "../../../shared/ui/PageHeader";
import { RequestSteps } from "../../../shared/ui/RequestSteps";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { isActionable } from "../../bridge";
import { fileUrl, projectRef } from "./api";
import { FileLinks } from "./FileLinks";
import { useStateLabels } from "./labels";
import { journalText } from "./model";
import { ProjectStatusTag, QuoteAcceptedTag } from "./status";
import { ActSlot, ContractSlot, JournalList, JournalTab } from "./Slots";

import "../decision/decision.css";
import "./projects.css";

type Tab = "contract" | "act";

function useOpenTab() {
  const { mobile } = useViewport();
  const [, setParams] = useSearchParams();
  return (tab: Tab) => {
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        // Телефон — лист на весь экран, планшет и десктоп — окно справа.
        if (mobile) {
          next.delete("panel");
          next.set("sheet", tab);
        } else {
          next.set("panel", "open");
        }
        next.set("tab", tab);
        return next;
      },
      { replace: true },
    );
  };
}

function Money({ value }: { value: { amount: string; currency: string } | null | undefined }) {
  if (!value) return <>—</>;
  return (
    <MoneyText
      value={value.amount}
      {...(value.currency === "UZS" ? {} : { currency: value.currency })}
    />
  );
}

function historyNote(
  t: ReturnType<typeof useTranslation<"projects">>["t"],
  date: (value: string, style?: "date" | "datetime") => string,
  entry: ProjectCard["journal"][number] | undefined,
): string | undefined {
  if (!entry) return undefined;
  const who = entry.actor_name ? ` · ${entry.actor_name}` : "";
  return `${journalText(t, entry)}, ${date(entry.at)}${who}`;
}

function InvoiceRows({ card, objectId }: { card: ProjectCard; objectId: string }) {
  const { t } = useTranslation("projects");
  const { me } = useAuth();
  const { date } = useFormat();
  const linkable = canSee(me, { resource: "eds.payments" }) && isActionable("/eds/payments");
  const action = (invoice: ProjectInvoice) => (
    <>
      {invoice.has_pdf ? (
        <FileLinks
          items={[
            {
              url: fileUrl(objectId, "invoice", invoice.id, "pdf"),
              label: t("card.documents.file"),
              name: `${invoice.number}.pdf`,
            },
          ]}
        />
      ) : null}
      {linkable ? (
        <LinkButton size="small" to="/eds/payments">
          {t("card.documents.payments")}
        </LinkButton>
      ) : null}
    </>
  );
  if (card.invoices.length === 0) {
    return (
      <DocRow
        number="—"
        type={t("card.documents.invoice")}
        status={<span className="pf-hint">{t("card.documents.invoiceMissing")}</span>}
      />
    );
  }
  return (
    <>
      {card.invoices.map((invoice) => (
        <DocRow
          key={invoice.id}
          number={invoice.number}
          type={t("card.documents.invoiceType")}
          status={<ProjectStatusTag kind="invoice" status={invoice.status} />}
          note={
            invoice.due_date && invoice.status !== "paid"
              ? t("card.documents.invoiceDue", { date: date(invoice.due_date) })
              : undefined
          }
          action={action(invoice)}
        />
      ))}
      {linkable ? null : (
        <li className="pf-doc pf-doc--note">
          <p className="pf-hint">{t("card.documents.invoiceHint")}</p>
        </li>
      )}
    </>
  );
}

function Documents({ card, objectId }: { card: ProjectCard; objectId: string }) {
  const { t } = useTranslation("projects");
  const { me } = useAuth();
  const { date } = useFormat();
  const open = useOpenTab();
  const quote = card.quote;
  const contract = card.contract;
  const act = card.act;
  const canOpenQuote = quote !== null && canSee(me, { resource: "eds.drafts" });
  const canCreate = card.can_create_contract;
  const canIssueAct = act === null && card.act_blocker === null;

  return (
    <DocList title={t("card.documents.title")}>
      {quote ? (
        <DocRow
          number={quote.number || "—"}
          type={t("card.documents.quoteType", { version: quote.version })}
          status={<QuoteAcceptedTag />}
          note={
            quote.outgoing_number
              ? `${quote.outgoing_number}${quote.valid_until ? ` · ${date(quote.valid_until)}` : ""}`
              : undefined
          }
          action={
            canOpenQuote && quote.number ? (
              <LinkButton
                size="small"
                to={`/eds/drafts/${encodeURIComponent(quote.number)}`}
                aria-label={t("card.documents.openQuoteLabel", { number: quote.number })}
              >
                {t("card.documents.openQuote")}
              </LinkButton>
            ) : null
          }
        />
      ) : null}

      {contract ? (
        <DocRow
          number={contract.number}
          type={t("card.documents.contractType")}
          status={
            <ProjectStatusTag kind="contract" status={contract.status}>
              {contract.status === "project" && contract.sent_to_client
                ? `${t("status.contract.project")} · ${t("contract.toClientYes")}`
                : undefined}
            </ProjectStatusTag>
          }
          note={historyNote(t, date, contract.history[0])}
          action={
            <Button
              size="small"
              type={contract.actions.length > 0 ? "primary" : "default"}
              aria-label={t("card.documents.openContractLabel", { number: contract.number })}
              onClick={() => {
                open("contract");
              }}
            >
              {t("card.documents.openContract")}
            </Button>
          }
        />
      ) : (
        <DocRow
          number="—"
          type={t("card.documents.contract")}
          status={<span className="pf-hint">{t("card.documents.contractMissing")}</span>}
          action={
            canCreate ? (
              <Button
                size="small"
                type="primary"
                aria-label={t("card.documents.createContractLabel")}
                onClick={() => {
                  open("contract");
                }}
              >
                {t("card.documents.createContract")}
              </Button>
            ) : null
          }
        />
      )}

      <InvoiceRows card={card} objectId={objectId} />

      {act ? (
        <DocRow
          number={act.number}
          type={t("card.documents.actType")}
          status={<ProjectStatusTag kind="act" status={act.status} />}
          note={historyNote(t, date, act.history[0])}
          action={
            <Button
              size="small"
              type={act.actions.length > 0 ? "primary" : "default"}
              aria-label={t("card.documents.openActLabel", { number: act.number })}
              onClick={() => {
                open("act");
              }}
            >
              {t("card.documents.openAct")}
            </Button>
          }
        />
      ) : (
        <DocRow
          number="—"
          type={t("card.documents.act")}
          status={<span className="pf-hint">{t("card.documents.actMissing")}</span>}
          action={
            canIssueAct ? (
              <Button
                size="small"
                type="primary"
                aria-label={t("card.documents.issueActLabel")}
                onClick={() => {
                  open("act");
                }}
              >
                {t("card.documents.issueAct")}
              </Button>
            ) : null
          }
        />
      )}
    </DocList>
  );
}

function Execution({ card }: { card: ProjectCard }) {
  const { t } = useTranslation("projects");
  const { date } = useFormat();
  const f = card.fulfillment;
  return (
    <Card size="small" title={<h2 className="pf-dec-title">{t("card.execution.title")}</h2>}>
      <p className="pf-hint" style={{ marginTop: 0 }}>
        {t("card.execution.hint")}
      </p>
      <div className="pf-proj-exec">
        <section aria-label={t("card.execution.shipment")}>
          <h3 className="pf-dec-subhead">{t("card.execution.shipment")}</h3>
          {f ? (
            <DefinitionList
              items={[
                { label: t("card.execution.status"), value: f.status_name },
                {
                  label: t("card.execution.expected"),
                  value: f.expected_delivery_date ? date(f.expected_delivery_date) : null,
                },
                {
                  label: t("card.execution.shipped"),
                  value: f.shipped_at ? date(f.shipped_at) : null,
                },
                {
                  label: t("card.execution.delivered"),
                  value: f.delivered_at ? date(f.delivered_at) : null,
                },
                {
                  label: t("card.execution.accepted"),
                  value: f.accepted_at ? date(f.accepted_at) : null,
                },
                { label: t("card.execution.carrier"), value: f.carrier },
                { label: t("card.execution.tracking"), value: f.tracking_number },
              ]}
            />
          ) : (
            <p className="pf-hint">{t("card.execution.none")}</p>
          )}
        </section>
        <section aria-label={t("card.execution.lines")}>
          <h3 className="pf-dec-subhead">{t("card.execution.lines")}</h3>
          {card.delivery_lines.length === 0 ? (
            <p className="pf-hint">{t("card.execution.linesNone")}</p>
          ) : (
            <ul className="pf-proj-lines">
              {card.delivery_lines.map((line) => (
                <li key={line.line_no}>
                  <span>
                    {line.title}
                    {line.quantity !== null ? ` · ${String(line.quantity)} ${line.unit}` : ""}
                  </span>
                  <span className="pf-hint">
                    {t(`card.execution.lineStatus.${line.status}`, { defaultValue: line.status })}
                    {line.eta ? ` · ${t("card.execution.line.eta")} ${date(line.eta)}` : ""}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </Card>
  );
}

function Requisites({ card }: { card: ProjectCard }) {
  const { t } = useTranslation("projects");
  const { date } = useFormat();
  return (
    <DefinitionList
      items={[
        { label: t("card.fields.client"), value: card.client_name },
        { label: t("card.fields.request"), value: card.request_number },
        { label: t("card.fields.total"), value: card.total ? <Money value={card.total} /> : null },
        { label: t("card.fields.manager"), value: card.manager?.name },
        { label: t("card.fields.responsible"), value: card.responsible?.name },
        { label: t("card.fields.opened"), value: date(card.created_at) },
        { label: t("card.fields.quote"), value: card.quote?.number },
        { label: t("card.fields.due"), value: card.due_date ? date(card.due_date) : null },
        {
          label: t("card.fields.clientStatus"),
          value: t(`clientStatus.${card.client_status}`),
        },
      ]}
    />
  );
}

function Content({ card, objectId }: { card: ProjectCard; objectId: string }) {
  const { t } = useTranslation("projects");
  const { me } = useAuth();
  // Действия по договору и акту — директор и бухгалтер (`eds.projects` полный); что именно сейчас можно, решает ERP.
  const writer = canEdit(me, "eds.projects");
  const problems = card.problems;
  const note: ReactNode =
    card.step === "DONE" ? (
      <p className="pf-proj-done">{t("card.doneNote")}</p>
    ) : (
      <p className="pf-hint">{t("card.doneRule")}</p>
    );
  return (
    <div className="pf-dec-page">
      <PageHeader
        title={t("card.title", { number: card.number })}
        subtitle={card.title}
        extra={
          <div className="pf-dec-row">
            <StatusTag tone={card.step === "DONE" ? "green" : "blue"}>
              {t(`clientStatus.${card.client_status}`)}
            </StatusTag>
            {problems.map((p) => (
              <StatusTag key={p} tone="red">
                {t(`problem.${p}`)}
              </StatusTag>
            ))}
            {writer ? null : <StatusTag tone="default">{t("card.readOnly")}</StatusTag>}
          </div>
        }
      />
      <section className="pf-card pf-dec-steps" aria-label={t("card.steps")}>
        <RequestSteps stage={card.step} number={card.request_number} />
      </section>
      {note}
      {writer ? null : <p className="pf-hint">{t("card.readOnlyHint")}</p>}
      <div className="pf-dec-grid pf-dec-grid--quote">
        <div className="pf-dec-main">
          <Documents card={card} objectId={objectId} />
          <Execution card={card} />
          <Card size="small" title={<h2 className="pf-dec-title">{t("card.journal.title")}</h2>}>
            {card.journal.length === 0 ? (
              <p className="pf-hint">{t("card.journal.empty")}</p>
            ) : (
              <JournalList card={card} />
            )}
          </Card>
        </div>
        <aside className="pf-dec-side" aria-label={t("card.fields.client")}>
          <Card size="small" title={<h2 className="pf-dec-title">{t("card.fields.client")}</h2>}>
            <Requisites card={card} />
          </Card>
        </aside>
      </div>
      <ContractSlot card={card} objectId={objectId} />
      <ActSlot card={card} objectId={objectId} />
      <JournalTab card={card} />
    </div>
  );
}

/** Карточка проекта (SPEC-v3 §7.3 «Все проекты»): шкала, документы КП · Договор · Счёт · Акт с историей и действиями, исполнение, журнал. */
export function ProjectView({ objectId }: { objectId: string }) {
  const { t } = useTranslation("projects");
  const query = useGetEdsProject(projectRef(objectId));
  const labels = useStateLabels();
  useDocumentTitle(t("card.title", { number: query.data?.number ?? objectId }));

  const error = query.error;
  if (error instanceof ApiError && error.status === 404) {
    return (
      <EmptyState
        title={t("state.notFound.title")}
        text={t("state.notFound.text")}
        action={<LinkButton to="/eds/projects">{t("state.notFound.action")}</LinkButton>}
      />
    );
  }
  if (query.isPending) {
    return (
      <div className="pf-dec-page">
        <Skeleton active paragraph={{ rows: 6 }} />
      </div>
    );
  }
  return (
    <QueryState query={query} labels={labels}>
      {(card) => <Content card={card} objectId={objectId} />}
    </QueryState>
  );
}
