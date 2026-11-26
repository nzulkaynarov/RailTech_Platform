import { App, Button } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { ProjectActActionsItem, ProjectCard } from "../../../shared/api/generated/model";
import {
  useActEdsProjectAct,
  useScanEdsProjectAct,
} from "../../../shared/api/generated/platform-bff";
import { useFormat } from "../../../shared/lib/useFormat";
import { DefinitionList } from "../../../shared/ui/DefinitionList";
import { ActionToggle } from "../../../shared/ui/FormParts";
import { MoneyText } from "../../../shared/ui/MoneyText";
import { fileUrl, projectRef } from "./api";
import { reasonText } from "./errors";
import { ActStatusTag } from "./status";
import { useAboutDocument } from "./aboutDocument";
import { FileLinks } from "./FileLinks";
import { ReasonForm, ScanForm } from "./forms";
import { actStateKey } from "./model";
import { SigningButton } from "./SigningButton";
import { useApplyCard } from "./useProjectMutations";

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
  const about = useAboutDocument();
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

  // Акта ещё нет: «Выпустить акт» живёт в строке документа (`ActIssueButton`).
  if (!act) return null;

  const may = (action: ProjectActActionsItem) => act.actions.includes(action);
  return (
    <div className={`pf-dec-panel pf-dec--${variant}`}>
      <section className="pf-dec-brief" aria-label={t("act.number", { number: act.number })}>
        <p className="pf-dec-note" style={{ margin: 0 }}>
          {t(`act.state.${actStateKey(act)}`)}
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
                <MoneyText value={act.total.amount} currency={act.total.currency} />
              ) : null,
            },
            { label: t("act.fields.issued"), value: act.issued_at ? date(act.issued_at) : null },
            {
              label: t(
                act.has_scan || act.status !== "signed"
                  ? "act.fields.signed"
                  : "act.fields.accepted",
              ),
              value: act.signed_at ? date(act.signed_at, "datetime") : null,
            },
          ]}
        />
        <FileLinks
          about={about({
            kind: t("card.documents.act"),
            number: act.number,
            on: act.issued_at,
            status: <ActStatusTag act={act} />,
            client: card.client_name,
          })}
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

      {/* План 0.7 (FR-30): подписанный или отменённый акт на подпись не отправляют */}
      {act.status !== "signed" && act.status !== "cancelled" ? (
        <SigningButton objectId={objectId} kind="act" documentId={act.id} />
      ) : null}
    </div>
  );
}

/** Кнопка строки «Акт»: выпустить акт, когда договор и поставка это позволяют (тот же вызов, что был во вкладке окна). */
export function ActIssueButton({ objectId }: { objectId: string }) {
  const { t } = useTranslation("projects");
  const { message } = App.useApp();
  const apply = useApplyCard(objectId);
  const [error, setError] = useState<string | null>(null);
  const run = useActEdsProjectAct({
    mutation: {
      onError: (e) => {
        setError(t("errors.failed", { reason: reasonText(t, e) }));
      },
    },
  });
  return (
    <>
      <Button
        size="small"
        type="primary"
        aria-label={t("card.documents.issueActLabel")}
        loading={run.isPending}
        disabled={run.isPending}
        onClick={() => {
          setError(null);
          run.mutate(
            { ref: projectRef(objectId), data: { action: "issue" } },
            {
              onSuccess: (next) => {
                apply(next);
                void message.success(t("act.done.issue"));
              },
            },
          );
        }}
      >
        {t("card.documents.issueAct")}
      </Button>
      {error ? (
        <p className="pf-field-error" role="alert">
          {error}
        </p>
      ) : null}
    </>
  );
}

/** Действия по акту в строке документа: скан, перевыпуск, возврат, отправка на подпись. Что можно — решает ERP. */
export function ActPanel({ card, objectId }: { card: ProjectCard; objectId: string }) {
  return <ActBody card={card} objectId={objectId} variant="panel" />;
}
