import { Card, Skeleton } from "antd";
import { useTranslation } from "react-i18next";

import { ApiError } from "../../../shared/api/errors";
import type { PaymentMemoCard } from "../../../shared/api/generated/model";
import { useGetPaymentMemo } from "../../../shared/api/generated/platform-bff";
import { useDocumentTitle } from "../../../shared/lib/useDocumentTitle";
import { useFormat } from "../../../shared/lib/useFormat";
import { DefinitionList } from "../../../shared/ui/DefinitionList";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { QueryState } from "../../../shared/ui/FormParts";
import { LinkButton } from "../../../shared/ui/LinkButton";
import { MoneyText } from "../../../shared/ui/MoneyText";
import { PageHeader } from "../../../shared/ui/PageHeader";
import { RecordHistory, type RecordHistoryEntry } from "../../../shared/ui/RecordHistory";
import { DecisionCenter } from "../decision/DecisionCenter";
import { RecordTab } from "../decision/RecordTab";
import { MemoFiles, MemoPanel, MemoStatus } from "./MemoPanel";
import { useStateLabels } from "./labels";
import { moneyProps } from "./model";
import { PageFrame } from "../../../shared/ui/PageFrame";

function Content({ memo }: { memo: PaymentMemoCard }) {
  const { t } = useTranslation("payments");
  const { date } = useFormat();
  const history: RecordHistoryEntry[] = memo.journal.map((entry) => ({
    at: entry.at,
    by: entry.by ? entry.by.full_name : null,
    action: t(`memo.journalAction.${entry.action.replace(".", "_")}`, {
      defaultValue: t("memo.journalActionUnknown"),
    }),
    comment: entry.comment ?? null,
  }));
  return (
    <PageFrame layout="object">
      <div className="pf-dec-page pf-overlay-aware">
        <PageHeader
          title={memo.number ?? memo.subject}
          {...(memo.number ? { subtitle: memo.subject } : {})}
          extra={
            <div className="pf-dec-row">
              <MemoStatus status={memo.status} />
              <LinkButton to="/eds/payments?show=memos">{t("view.backMemos")}</LinkButton>
            </div>
          }
        />
        <Card size="small" title={<h2 className="pf-dec-title">{t("memo.panel.text")}</h2>}>
          <p className="pf-dec-text">{memo.text}</p>
        </Card>
        <Card size="small" title={<h2 className="pf-dec-title">{t("memo.panel.files")}</h2>}>
          <MemoFiles memo={memo} />
        </Card>
        <DecisionCenter
          legacyTab="payment"
          legacySheet="payment"
          label={t("memo.panel.sheetLabel")}
        >
          <MemoPanel memoId={memo.id} />
        </DecisionCenter>
        <RecordTab tab="facts">
          <DefinitionList
            items={[
              { label: t("memo.panel.from"), value: memo.author.full_name },
              {
                label: t("memo.panel.amount"),
                value: memo.amount ? <MoneyText {...moneyProps(memo.amount)} /> : null,
              },
              { label: t("memo.panel.due"), value: memo.due_date ? date(memo.due_date) : null },
              {
                label: t("brief.project"),
                value: memo.deal ? (memo.deal.number ?? String(memo.deal.erp_deal_id)) : null,
              },
            ]}
          />
        </RecordTab>
        {history.length > 0 ? (
          <RecordTab tab="history">
            <RecordHistory label={t("memo.panel.journal")} entries={history} />
          </RecordTab>
        ) : null}
      </div>
    </PageFrame>
  );
}

/** Карточка служебки к оплате: текст, счёт поставщика, журнал; «Оплачено» — в боковом окне. */
export function MemoView({ id }: { id: string }) {
  const { t } = useTranslation("payments");
  const query = useGetPaymentMemo(id);
  const labels = useStateLabels();
  useDocumentTitle(query.data?.number ?? query.data?.subject);
  const error = query.error;
  if (error instanceof ApiError && error.status === 404) {
    return (
      <EmptyState
        title={t("state.memoNotFound.title")}
        text={t("state.memoNotFound.text")}
        action={
          <LinkButton to="/eds/payments?show=memos">{t("state.memoNotFound.action")}</LinkButton>
        }
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
      {(memo) => <Content memo={memo} />}
    </QueryState>
  );
}
