import { App, Button } from "antd";
import { type ReactNode, useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  ProjectCard,
  ProjectContractActionInAction,
  ProjectContractActionsItem,
} from "../../../shared/api/generated/model";
import {
  useActEdsProjectContract,
  useCreateEdsProjectContract,
  useScanEdsProjectContract,
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
import { NoteField, ReasonForm, ScanForm } from "./forms";
import { contractStateKey, journalText } from "./model";
import { ProjectStatusTag } from "./status";
import { useApplyCard } from "./useProjectMutations";

type Action = ProjectContractActionInAction;
const FINAL: ReadonlySet<string> = new Set(["signed", "cancelled"]);

/** Что делает главная кнопка в каждом статусе договора (SPEC-v3 §7.3, вкладка «Договор»); остальное — вторичные действия. */
function primaryOf(
  card: ProjectCard,
  allowed: readonly ProjectContractActionsItem[],
): Action | "attach_scan" | null {
  const contract = card.contract;
  if (!contract) return null;
  const pick = (action: ProjectContractActionsItem) => (allowed.includes(action) ? action : null);
  switch (contract.status) {
    case "project":
      return contract.sent_to_client ? pick("client_agreed") : pick("send_to_client");
    case "client_agreed":
      return pick("mark_issued");
    case "issued_at_operator":
      return pick("attach_scan");
    case "rejected":
      return pick("revise");
    default:
      return null;
  }
}

function ContractBody({
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
  const contract = card.contract;
  const [note, setNote] = useState("");
  // Какое действие сейчас выполняется: кнопка следующего шага, появившаяся с новой карточкой, не должна вертеться.
  const [pending, setPending] = useState<string | null>(null);
  const [rejecting, setRejecting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fail = (e: unknown) => {
    setPending(null);
    setError(t("errors.failed", { reason: reasonText(t, e) }));
  };
  const done = (next: ProjectCard, key: string) => {
    setPending(null);
    setError(null);
    setNote("");
    setRejecting(false);
    apply(next);
    void message.success(t(`contract.done.${key}`));
    onDone?.();
  };
  const act = useActEdsProjectContract({ mutation: { onError: fail } });
  const scan = useScanEdsProjectContract({ mutation: { onError: fail } });
  const create = useCreateEdsProjectContract({ mutation: { onError: fail } });
  const busy = act.isPending || scan.isPending || create.isPending;

  if (!contract) {
    return (
      <div className="pf-dec-panel">
        <EmptyState
          level={3}
          compact
          title={t("contract.none.title")}
          text={t("contract.none.text")}
        />
        {card.can_create_contract ? (
          <div className="pf-fp-form">
            <Consequence
              title={t("contract.none.consequence.title")}
              items={[
                t("contract.none.consequence.step1"),
                t("contract.none.consequence.step2"),
                t("contract.none.consequence.step3"),
              ]}
            />
            {error ? (
              <p className="pf-field-error" role="alert">
                {error}
              </p>
            ) : null}
            <Button
              type="primary"
              block
              loading={pending === "create"}
              disabled={busy}
              onClick={() => {
                setError(null);
                setPending("create");
                create.mutate(
                  { ref },
                  {
                    onSuccess: (next) => {
                      done(next, "create");
                    },
                  },
                );
              }}
            >
              {t("contract.none.create")}
            </Button>
          </div>
        ) : (
          <p className="pf-hint">{t("contract.readOnly")}</p>
        )}
      </div>
    );
  }

  const allowed = contract.actions;
  const primary = primaryOf(card, allowed);
  const may = (action: ProjectContractActionsItem) => allowed.includes(action);
  const send = (action: Action, extra: { reason?: string; note?: string } = {}) => {
    setError(null);
    setPending(action);
    act.mutate(
      { ref, data: { action, ...extra } },
      {
        onSuccess: (next) => {
          done(next, action);
        },
      },
    );
  };
  const items: HistoryItem[] = contract.history.map((entry) => ({
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

  let primaryBlock: ReactNode = null;
  if (primary === "attach_scan") {
    primaryBlock = (
      <>
        <Consequence
          title={t("contract.consequence.title")}
          items={t("contract.consequence.attach_scan", { returnObjects: true }) as string[]}
        />
        <ScanForm
          labels={{
            label: t("contract.scan.label"),
            hint: t("contract.scan.hint"),
            submit: t("contract.scan.submit"),
            choose: t("contract.scan.choose"),
          }}
          busy={scan.isPending}
          error={error}
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
    );
  } else if (primary !== null) {
    const lines = t(`contract.consequence.${primary}`, { returnObjects: true }) as string[];
    primaryBlock = (
      <form
        key={primary}
        className="pf-fp-form"
        aria-label={t(`contract.action.${primary}`)}
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          if (!busy)
            send(primary, primary === "mark_issued" && note.trim() ? { note: note.trim() } : {});
        }}
      >
        {primary === "mark_issued" ? (
          <NoteField
            label={t("contract.note.label")}
            hint={t("contract.note.hint")}
            placeholder={t("contract.note.placeholder")}
            value={note}
            onChange={setNote}
          />
        ) : null}
        <Consequence title={t("contract.consequence.title")} items={lines} />
        {error && !rejecting ? (
          <p className="pf-field-error" role="alert">
            {error}
          </p>
        ) : null}
        <Button
          type="primary"
          htmlType="submit"
          block
          loading={pending === primary && !rejecting}
          disabled={busy}
        >
          {t(`contract.action.${primary}`)}
        </Button>
      </form>
    );
  }

  const canReject = may("reject");
  const stateKey = contractStateKey(contract);
  return (
    <div className={`pf-dec-panel pf-dec--${variant}`}>
      <section
        className="pf-dec-brief"
        aria-label={t("contract.number", { number: contract.number })}
      >
        <div className="pf-dec-brief-head">
          <h3 className="pf-fp-title">{t("contract.number", { number: contract.number })}</h3>
          <ProjectStatusTag kind="contract" status={contract.status} />
        </div>
        <p className="pf-dec-note" style={{ margin: 0 }}>
          {t(`contract.state.${stateKey}`)}
        </p>
        <DefinitionList
          items={[
            {
              label: t("contract.fields.total"),
              value: contract.total ? (
                <MoneyText value={contract.total.amount} currency={contract.total.currency} />
              ) : null,
            },
            { label: t("contract.fields.created"), value: date(contract.created_at) },
            {
              label: t("contract.fields.toClient"),
              value:
                contract.status === "project"
                  ? contract.sent_to_client
                    ? t("contract.toClientYes")
                    : t("contract.toClientNo")
                  : null,
            },
            {
              label: t("contract.fields.agreed"),
              value: contract.client_agreed_at ? date(contract.client_agreed_at, "datetime") : null,
            },
            {
              label: t("contract.fields.signed"),
              value: contract.signed_at ? date(contract.signed_at, "datetime") : null,
            },
          ]}
        />
        <FileLinks
          items={[
            contract.has_pdf
              ? {
                  url: fileUrl(objectId, "contract", contract.id, "pdf"),
                  label: t("contract.files.pdf"),
                  name: `${contract.number}.pdf`,
                }
              : null,
            contract.has_scan
              ? {
                  url: fileUrl(objectId, "contract", contract.id, "scan"),
                  label: t("contract.files.scan"),
                  name: `${contract.number}-scan`,
                }
              : null,
          ]}
        />
      </section>

      {primaryBlock}
      {allowed.length === 0 && !FINAL.has(contract.status) ? (
        <p className="pf-hint">{t("contract.readOnly")}</p>
      ) : null}

      {canReject ? (
        <ActionToggle
          label={t("contract.action.reject")}
          open={rejecting}
          danger
          disabled={busy}
          onToggle={setRejecting}
        >
          <ReasonForm
            labels={{
              title: t("contract.reject.title"),
              label: t("contract.reject.reason.label"),
              hint: t("contract.reject.reason.hint"),
              submit: t("contract.reject.submit"),
              cancel: t("contract.reject.cancel"),
              disabled: t("contract.reject.disabled"),
            }}
            busy={act.isPending}
            error={rejecting ? error : null}
            onSubmit={(reason) => {
              send("reject", { reason });
            }}
            onCancel={() => {
              setRejecting(false);
              setError(null);
            }}
          />
        </ActionToggle>
      ) : null}

      <section aria-label={t("contract.history")}>
        <h3 className="pf-dec-subhead">{t("contract.history")}</h3>
        {items.length > 0 ? (
          <History items={items} label={t("contract.history")} />
        ) : (
          <p className="pf-hint">{t("contract.historyEmpty")}</p>
        )}
      </section>
    </div>
  );
}

/** Содержимое вкладки «Договор» бокового окна карточки проекта. */
export function ContractPanel({
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
  // Что можно сделать, решает ERP по статусу и правам роли (`contract.actions`), экран только показывает.
  return <ContractBody card={card} objectId={objectId} variant={variant} onDone={onDone} />;
}
