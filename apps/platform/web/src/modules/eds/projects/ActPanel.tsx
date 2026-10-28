import { App, Button } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { ProjectActActionsItem, ProjectCard } from "../../../shared/api/generated/model";
import {
  useActEdsProjectAct,
  useScanEdsProjectAct,
} from "../../../shared/api/generated/platform-bff";
import { useFormat } from "../../../shared/lib/useFormat";
import { Consequence } from "../../../shared/ui/Consequence";
import { DefinitionList } from "../../../shared/ui/DefinitionList";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { ActionToggle } from "../../../shared/ui/FormParts";
import { History, type HistoryItem } from "../../../shared/ui/History";
import { MoneyText } from "../../../shared/ui/MoneyText";
import { fileUrl, projectRef } from "./api";
import { reasonText } from "./errors";
import { FileLinks } from "./FileLinks";
import { ReasonForm, ScanForm } from "./forms";
import { journalText } from "./model";
import { ProjectStatusTag } from "./status";
import { useApplyCard } from "./useProjectMutations";

function NoAct({
  card,
  busy,
  error,
  onIssue,
}: {
  card: ProjectCard;
  busy: boolean;
  error: string | null;
  onIssue: () => void;
}) {
  const { t } = useTranslation("projects");
  const blocker = card.act_blocker;
  if (blocker === "forbidden") {
    return (
      <EmptyState level={3} compact title={t("act.none.title")} text={t("act.none.forbidden")} />
    );
  }
  if (blocker === "no_invoice") {
    return (
      <EmptyState level={3} compact title={t("act.none.title")} text={t("act.none.noInvoice")} />
    );
  }
  return (
    <div className="pf-dec-panel">
      <EmptyState level={3} compact title={t("act.none.title")} text={t("act.none.ready")} />
      <div className="pf-fp-form">
        <Consequence
          title={t("act.consequence.title")}
          items={t("act.none.consequence", { returnObjects: true }) as string[]}
        />
        {error ? (
          <p className="pf-field-error" role="alert">
            {error}
          </p>
        ) : null}
        <Button type="primary" block loading={busy} disabled={busy} onClick={onIssue}>
          {t("act.none.issue")}
        </Button>
      </div>
    </div>
  );
}

function ActBody({
  card,
  objectId,
  variant,
  onDone,
}: {
  card: ProjectCard;
  objectId: string;
  variant: "panel" | "sheet";
  onDone?: (() => void) | undefined;
}) {
  const { t } = useTranslation("projects");
  const { date } = useFormat();
  const { message } = App.useApp();
  const apply = useApplyCard(objectId);
  const ref = projectRef(objectId);
  const act = card.act;
  const [returning, setReturning] = useState(false);
  // Какое действие выполняется сейчас: кнопка, появившаяся с новой карточкой, не должна вертеться.
  const [pending, setPending] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const fail = (e: unknown) => {
    setPending(null);
    setError(t("errors.failed", { reason: reasonText(t, e) }));
  };
  const done = (next: ProjectCard, key: string) => {
    setPending(null);
    setError(null);
    setReturning(false);
    apply(next);
    void message.success(t(`act.done.${key}`));
    onDone?.();
  };
  const run = useActEdsProjectAct({ mutation: { onError: fail } });
  const scan = useScanEdsProjectAct({ mutation: { onError: fail } });
  const busy = run.isPending || scan.isPending;

  if (!act) {
    return (
      <NoAct
        card={card}
        busy={pending === "issue"}
        error={error}
        onIssue={() => {
          setError(null);
          setPending("issue");
          run.mutate(
            { ref, data: { action: "issue" } },
            {
              onSuccess: (next) => {
                done(next, "issue");
              },
            },
          );
        }}
      />
    );
  }

  const may = (action: ProjectActActionsItem) => act.actions.includes(action);
  const items: HistoryItem[] = act.history.map((entry) => ({
    state: "done",
    title: journalText(t, entry),
    meta: (
      <>
        {entry.actor_name
          ? t("journal.by", { date: date(entry.at, "datetime"), name: entry.actor_name })
          : t("journal.bySystem", { date: date(entry.at, "datetime") })}
        {entry.reason ? (
          <span className="pf-dec-note">{t("journal.reason", { reason: entry.reason })}</span>
        ) : null}
      </>
    ),
  }));

  return (
    <div className={`pf-dec-panel pf-dec--${variant}`}>
      <section className="pf-dec-brief" aria-label={t("act.number", { number: act.number })}>
        <div className="pf-dec-brief-head">
          <h3 className="pf-fp-title">{t("act.number", { number: act.number })}</h3>
          <ProjectStatusTag kind="act" status={act.status} />
        </div>
        <p className="pf-dec-note" style={{ margin: 0 }}>
          {t(`act.state.${act.status}`)}
        </p>
        {act.rejection_reason && act.status === "returned" ? (
          <p className="pf-dec-note" style={{ margin: 0 }}>
            {t("act.returnedReason", { reason: act.rejection_reason })}
          </p>
        ) : null}
        <DefinitionList
          items={[
            {
              label: t("act.fields.total"),
              value: act.total ? (
                <MoneyText
                  value={act.total.amount}
                  {...(act.total.currency === "UZS" ? {} : { currency: act.total.currency })}
                />
              ) : null,
            },
            { label: t("act.fields.issued"), value: act.issued_at ? date(act.issued_at) : null },
            {
              label: t("act.fields.signed"),
              value: act.signed_at ? date(act.signed_at, "datetime") : null,
            },
          ]}
        />
        <FileLinks
          items={[
            act.has_pdf
              ? {
                  url: fileUrl(objectId, "act", act.id, "pdf"),
                  label: t("act.files.pdf"),
                  name: `${act.number}.pdf`,
                }
              : null,
            act.has_scan
              ? {
                  url: fileUrl(objectId, "act", act.id, "scan"),
                  label: t("act.files.scan"),
                  name: `${act.number}-scan`,
                }
              : null,
          ]}
        />
      </section>

      {may("attach_scan") ? (
        <>
          <Consequence
            title={t("act.consequence.title")}
            items={t("act.consequence.attach_scan", { returnObjects: true }) as string[]}
          />
          <ScanForm
            labels={{
              label: t("act.scan.label"),
              hint: t("act.scan.hint"),
              submit: t("act.scan.submit"),
              choose: t("act.scan.choose"),
            }}
            busy={scan.isPending}
            error={returning ? null : error}
            onSubmit={(file) => {
              setError(null);
              scan.mutate(
                { ref, data: { file } },
                {
                  onSuccess: (next) => {
                    done(next, "attach_scan");
                  },
                },
              );
            }}
          />
        </>
      ) : null}

      {may("reissue") ? (
        <div className="pf-fp-form">
          <Consequence
            title={t("act.consequence.title")}
            items={t("act.consequence.reissue", { returnObjects: true }) as string[]}
          />
          {error ? (
            <p className="pf-field-error" role="alert">
              {error}
            </p>
          ) : null}
          <Button
            type="primary"
            block
            loading={pending === "reissue"}
            disabled={busy}
            onClick={() => {
              setError(null);
              setPending("reissue");
              run.mutate(
                { ref, data: { action: "reissue" } },
                {
                  onSuccess: (next) => {
                    done(next, "reissue");
                  },
                },
              );
            }}
          >
            {t("act.action.reissue")}
          </Button>
        </div>
      ) : null}

      {may("return") ? (
        <ActionToggle
          label={t("act.action.return")}
          open={returning}
          danger
          disabled={busy}
          onToggle={setReturning}
        >
          <ReasonForm
            labels={{
              title: t("act.return.title"),
              label: t("act.return.reason.label"),
              hint: t("act.return.reason.hint"),
              submit: t("act.return.submit"),
              cancel: t("act.return.cancel"),
              disabled: t("act.return.disabled"),
            }}
            busy={run.isPending}
            error={returning ? error : null}
            onSubmit={(reason) => {
              setError(null);
              run.mutate(
                { ref, data: { action: "return", reason } },
                {
                  onSuccess: (next) => {
                    done(next, "return");
                  },
                },
              );
            }}
            onCancel={() => {
              setReturning(false);
              setError(null);
            }}
          />
        </ActionToggle>
      ) : null}

      {act.actions.length === 0 && act.status !== "signed" && act.status !== "cancelled" ? (
        <p className="pf-hint">{t("act.readOnly")}</p>
      ) : null}

      <section aria-label={t("act.history")}>
        <h3 className="pf-dec-subhead">{t("act.history")}</h3>
        {items.length > 0 ? (
          <History items={items} label={t("act.history")} />
        ) : (
          <p className="pf-hint">{t("act.historyEmpty")}</p>
        )}
      </section>
    </div>
  );
}

/** Содержимое вкладки «Акт» бокового окна карточки проекта. */
export function ActPanel({
  card,
  objectId,
  variant = "panel",
  onDone,
}: {
  card: ProjectCard;
  objectId: string;
  variant?: "panel" | "sheet";
  onDone?: (() => void) | undefined;
}) {
  return <ActBody card={card} objectId={objectId} variant={variant} onDone={onDone} />;
}
