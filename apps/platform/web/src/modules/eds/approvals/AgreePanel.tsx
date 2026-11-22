import { type ReactNode, useEffect } from "react";
import { useTranslation } from "react-i18next";

import { useAuth } from "../../../app/auth/useAuth";
import type { MemoApprovalCard } from "../../../shared/api/generated/model";
import { useGetMemoApproval } from "../../../shared/api/generated/platform-bff";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { QueryState } from "../../../shared/ui/FormParts";
import { AgreeForm } from "./AgreeForm";
import { memoRef } from "./api";
import { clearComment } from "./draft";
import { mayDecideMemos } from "./model";
import { useStepNote } from "./stepNote";
import { useStateLabels } from "./labels";

function PanelBody({ memo }: { memo: MemoApprovalCard }) {
  const { t } = useTranslation("approvals");
  const { me } = useAuth();
  // Заместитель решает шаг замещаемого и без раздела согласования (СЦ-9): право и замещение проверяет EDS
  const mayDecide = mayDecideMemos(me) || Boolean(memo.acting_for);
  const stepNote = useStepNote(memo);
  // Документ уже решён (в том числе другим): черновик комментария ему не нужен.
  useEffect(() => {
    if (memo.status !== "open") clearComment(me.id, memo.approval_id);
  }, [memo.status, memo.approval_id, me.id]);
  let body: ReactNode;
  if (memo.status === "open" && memo.can_decide && mayDecide) {
    body = <AgreeForm memo={memo} />;
  } else if (memo.status === "open") {
    body = (
      <EmptyState
        level={3}
        compact
        title={t("panel.readOnly.title")}
        text={mayDecide && stepNote ? stepNote : t("panel.readOnly.text")}
      />
    );
  } else {
    // Решённый документ говорит о себе статусом в шапке и лентой «Маршрут» (ЕД-7)
    body = null;
  }
  return <div className="pf-dec-panel pf-dec-page">{body}</div>;
}

/** Блок решения в центре карточки: форма для согласующего или пояснение, почему решает не он (ЕД-7). */
export function AgreePanel({ memoRef: ref }: { memoRef: string }) {
  const query = useGetMemoApproval(memoRef(ref));
  const labels = useStateLabels();
  return (
    <QueryState query={query} labels={labels} level={3} compact>
      {(memo) => <PanelBody memo={memo} />}
    </QueryState>
  );
}
