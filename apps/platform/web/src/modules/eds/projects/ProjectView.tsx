import { Card, Skeleton } from "antd";
import { Fragment, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";

import { canEdit, canSee } from "../../../app/access";
import { useAuth } from "../../../app/auth/useAuth";
import { ApiError } from "../../../shared/api/errors";
import type { ProjectCard, ProjectInvoice } from "../../../shared/api/generated/model";
import { useGetEdsProject } from "../../../shared/api/generated/platform-bff";
import { useDocumentTitle } from "../../../shared/lib/useDocumentTitle";
import { useFormat } from "../../../shared/lib/useFormat";
import { DefinitionList } from "../../../shared/ui/DefinitionList";
import { DoNotWorkStrip } from "../../../shared/ui/DoNotWorkStrip";
import { DocList, DocRow } from "../../../shared/ui/DocRow";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { QueryState } from "../../../shared/ui/FormParts";
import { LinkButton } from "../../../shared/ui/LinkButton";
import { PageHeader } from "../../../shared/ui/PageHeader";
import { RequestSteps } from "../../../shared/ui/RequestSteps";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { SigningButton } from "./SigningButton";
import { fileUrl, projectRef } from "./api";
import { FileLinks } from "./FileLinks";
import { DeliveryActions } from "./DeliveryMarks";
import { useStateLabels } from "./labels";
import { ActStatusTag, ProjectStatusTag, QuoteAcceptedTag } from "./status";
import { ActIssueButton, ActPanel } from "./ActPanel";
import { ContractCreateButton, ContractPanel } from "./ContractPanel";
import { DocumentClientLink } from "./DocumentClientLink";
import { ProjectFactsTab, ProjectHistoryTab } from "./Slots";
import { PageFrame } from "../../../shared/ui/PageFrame";

import "../decision/decision.css";
import "./projects.css";

function InvoiceRows({ card, objectId }: { card: ProjectCard; objectId: string }) {
  const { t } = useTranslation("projects");
  const { me } = useAuth();
  const { date } = useFormat();
  const linkable = canSee(me, { resource: "eds.payments" });
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
      <SigningButton objectId={objectId} kind="invoice" documentId={invoice.id} />
    </>
  );
  if (card.invoices.length === 0) {
    return (
      <DocRow
        number="—"
        type={t("card.documents.invoice")}
        status={
          <span className="pf-hint">
            {t(
              card.contract?.status === "signed"
                ? "card.documents.invoiceMissingSigned"
                : "card.documents.invoiceMissing",
            )}
          </span>
        }
      />
    );
  }
  return (
    <>
      {card.invoices.map((invoice) => (
        <Fragment key={invoice.id}>
          <DocRow
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
          <DocumentClientLink objectId={objectId} kind="invoice" documentId={invoice.id} />
        </Fragment>
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
        <>
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
          />
          <li className="pf-doc pf-doc--detail">
            <ContractPanel card={card} objectId={objectId} />
          </li>
          <DocumentClientLink objectId={objectId} kind="contract" documentId={contract.id} />
        </>
      ) : (
        <DocRow
          number="—"
          type={t("card.documents.contract")}
          status={<span className="pf-hint">{t("card.documents.contractMissing")}</span>}
          action={canCreate ? <ContractCreateButton objectId={objectId} /> : null}
        />
      )}

      <InvoiceRows card={card} objectId={objectId} />

      {act ? (
        <>
          <DocRow
            number={act.number}
            type={t("card.documents.actType")}
            status={<ActStatusTag act={act} />}
          />
          <li className="pf-doc pf-doc--detail">
            <ActPanel card={card} objectId={objectId} />
          </li>
          <DocumentClientLink objectId={objectId} kind="act" documentId={act.id} />
        </>
      ) : (
        <DocRow
          number="—"
          type={t("card.documents.act")}
          status={
            <span className="pf-hint">{actHint(card.act_blocker, t, contract !== null)}</span>
          }
          action={canIssueAct ? <ActIssueButton objectId={objectId} /> : null}
        />
      )}
    </DocList>
  );
}

/** Статус строки «Акт» из факта `act_blocker` (почему акт нельзя выпустить), а не общая фраза. */
function actHint(
  blocker: ProjectCard["act_blocker"],
  t: TFunction<"projects">,
  hasContract: boolean,
): string {
  switch (blocker) {
    case "no_invoice":
      // До договора счёта не будет и просить его выставить нельзя (ui-standard §14.2)
      return hasContract ? t("act.none.noInvoice") : t("card.documents.actMissing");
    case "forbidden":
      return t("act.none.forbidden");
    case "not_delivered":
      return t("card.documents.actAfterDelivery");
    case null:
      return t("act.none.ready");
    default:
      return t("card.documents.actMissing");
  }
}

function Execution({ card, objectId }: { card: ProjectCard; objectId: string }) {
  const { t } = useTranslation("projects");
  const { date, qty } = useFormat();
  const f = card.fulfillment;
  return (
    <Card size="small" title={<h2 className="pf-dec-title">{t("card.execution.title")}</h2>}>
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
                {
                  label: t("card.execution.proof"),
                  value: f.proof_url ? (
                    <a className="pf-focusable" href={f.proof_url} download>
                      {f.proof_name ?? t("card.execution.proofFile")}
                    </a>
                  ) : null,
                },
              ]}
            />
          ) : (
            <p className="pf-hint">{t("card.execution.none")}</p>
          )}
          {f?.goods_not_shipped ? (
            <p className="pf-hint">{t("card.execution.awaitingShipment")}</p>
          ) : null}
          {f ? <DeliveryActions objectId={objectId} fulfillment={f} /> : null}
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
                    {line.quantity !== null ? ` · ${qty(line.quantity)} ${line.unit}` : ""}
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
    <PageFrame layout="object">
      <div className="pf-dec-page pf-overlay-aware">
        <PageHeader
          title={t("card.title", { number: card.number })}
          subtitle={card.title}
          extra={
            <div className="pf-dec-row">
              {problems.length > 0 ? (
                // Один статус в шапке (СЦ-8): проблема важнее слова для клиента; где проект по пути — показывает шкала.
                <StatusTag tone="red">
                  {problems.map((p) => t(`problem.${p}`)).join(" · ")}
                </StatusTag>
              ) : (
                <StatusTag kind="stage" status={card.step}>
                  {t(`clientStatus.${card.client_status}`)}
                </StatusTag>
              )}
              {writer ? null : <StatusTag tone="default">{t("card.readOnly")}</StatusTag>}
            </div>
          }
        />
        <DoNotWorkStrip mark={card.do_not_work} />
        <section className="pf-card pf-dec-steps" aria-label={t("card.steps")}>
          <RequestSteps stage={card.step} number={card.request_number} />
        </section>
        {note}
        {writer ? null : <p className="pf-hint">{t("card.readOnlyHint")}</p>}
        <Documents card={card} objectId={objectId} />
        <Execution card={card} objectId={objectId} />
        <ProjectFactsTab card={card} />
        <ProjectHistoryTab card={card} />
      </div>
    </PageFrame>
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
