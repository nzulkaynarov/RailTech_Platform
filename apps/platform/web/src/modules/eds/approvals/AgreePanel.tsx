import { type ReactNode, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { canEdit } from "../../../app/access";
import { useAuth } from "../../../app/auth/useAuth";
import type { MemoApprovalCard } from "../../../shared/api/generated/model";
import { useGetMemoApproval } from "../../../shared/api/generated/platform-bff";
import { useFormat } from "../../../shared/lib/useFormat";
import { DefinitionList } from "../../../shared/ui/DefinitionList";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { QueryState } from "../../../shared/ui/FormParts";
import { MoneyText } from "../../../shared/ui/MoneyText";
import { DecisionSlot } from "../decision/DecisionSlot";
import { DocumentStatusTag } from "../documents/status";
import { AgreeForm } from "./AgreeForm";
import { memoPath, memoRef } from "./api";
import { clearComment } from "./draft";
import { useStateLabels } from "./labels";

function Brief({ memo }: { memo: MemoApprovalCard }) {
  const { t } = useTranslation("approvals");
  const { date } = useFormat();
  const label = memo.number ?? t(`kinds.${memo.kind}`);
  return (
    <section className="pf-dec-brief" aria-label={label}>
      <div className="pf-dec-brief-head">
        <h3 className="pf-fp-title">{label}</h3>
        <DocumentStatusTag kind="memo" status={memo.document_status} />
      </div>
      <p className="pf-dec-subject">{memo.subject}</p>
      <DefinitionList
        items={[
          { label: t("panel.brief.from"), value: memo.author.full_name },
          {
            label: t("panel.brief.amount"),
            value: memo.amount ? (
              <MoneyText
                value={memo.amount.amount}
                {...(memo.amount.currency === "UZS" ? {} : { currency: memo.amount.currency })}
              />
            ) : null,
          },
          { label: t("panel.brief.due"), value: memo.due_date ? date(memo.due_date) : null },
        ]}
      />
      <h4 className="pf-dec-subhead">{t("panel.brief.text")}</h4>
      <p className="pf-dec-text">{memo.text}</p>
      <Link className="pf-focusable pf-dec-open" to={memoPath(memo)}>
        {t("panel.briefOpen")}
      </Link>
    </section>
  );
}

function PanelBody({
  memo,
  variant,
  brief,
  onDone,
}: {
  memo: MemoApprovalCard;
  variant: "panel" | "sheet";
  brief: boolean;
  onDone?: (() => void) | undefined;
}) {
  const { t } = useTranslation("approvals");
  const { me } = useAuth();
  const mayDecide = canEdit(me, "eds.memo.approve");
  // Документ уже решён (в том числе другим): черновик комментария ему не нужен.
  useEffect(() => {
    if (memo.status !== "open") clearComment(me.id, memo.approval_id);
  }, [memo.status, memo.approval_id, me.id]);
  let body: ReactNode;
  if (memo.status === "open" && memo.can_decide && mayDecide) {
    body = <AgreeForm memo={memo} variant={variant} {...(onDone ? { onDone } : {})} />;
  } else if (memo.status === "open") {
    body = (
      <EmptyState
        level={3}
        compact
        title={t("panel.readOnly.title")}
        text={t(mayDecide ? "panel.readOnly.notYourStep" : "panel.readOnly.text")}
      />
    );
  } else {
    body = (
      <EmptyState
        level={3}
        compact
        title={t(`panel.decided.${memo.status}.title`)}
        text={t(`panel.decided.${memo.status}.text`)}
      />
    );
  }
  return (
    <div className="pf-dec-panel pf-dec-page">
      {brief ? <Brief memo={memo} /> : null}
      {body}
    </div>
  );
}

/** Содержимое вкладки «Согласование»: документ по `ref` (id или номер), форма для согласующего, пояснение автору. */
export function AgreePanel({
  memoRef: ref,
  brief = false,
  variant = "panel",
  onDone,
}: {
  memoRef: string;
  brief?: boolean;
  variant?: "panel" | "sheet";
  onDone?: (() => void) | undefined;
}) {
  const query = useGetMemoApproval(memoRef(ref));
  const labels = useStateLabels();
  return (
    <QueryState query={query} labels={labels} level={3} compact>
      {(memo) => <PanelBody memo={memo} variant={variant} brief={brief} onDone={onDone} />}
    </QueryState>
  );
}

function SheetTitle({ memoRef: ref }: { memoRef: string }) {
  const { t } = useTranslation("approvals");
  const query = useGetMemoApproval(memoRef(ref));
  const label = query.data ? (query.data.number ?? t(`kinds.${query.data.kind}`)) : null;
  return <>{label ? t("panel.sheetTitle", { number: label }) : t("panel.sheetLabel")}</>;
}

/** Где живёт «Согласование»: вкладка бокового окна каркаса, на телефоне — лист на весь экран (`?sheet=agree`). */
export function AgreeSlot({ memoRef: ref, brief = false }: { memoRef: string; brief?: boolean }) {
  const { t } = useTranslation("approvals");
  return (
    <DecisionSlot
      tab="agree"
      sheet="agree"
      title={<SheetTitle memoRef={ref} />}
      label={t("panel.sheetLabel")}
      closeLabel={t("panel.sheetClose")}
    >
      {(variant, onDone) => (
        <AgreePanel memoRef={ref} brief={brief} variant={variant} onDone={onDone} />
      )}
    </DecisionSlot>
  );
}
