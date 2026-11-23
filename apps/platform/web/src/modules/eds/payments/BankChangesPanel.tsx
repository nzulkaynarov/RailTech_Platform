import { Alert, Button, Input, Segmented } from "antd";
import { Dialog } from "../../../shared/ui/Dialog";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

import { canEdit } from "../../../app/access";
import { useAuth } from "../../../app/auth/useAuth";
import { ApiError } from "../../../shared/api/errors";
import type { BankChangeItem } from "../../../shared/api/generated/model";
import {
  useApproveBankChangeRequest,
  useListBankChangeRequests,
  useRejectBankChangeRequest,
} from "../../../shared/api/generated/platform-bff";
import { useFormat } from "../../../shared/lib/useFormat";
import { ListSkeleton } from "../../../shared/ui/DataBlock";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { FormField } from "../../../shared/ui/FormParts";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { isStepUpError, useStepUp } from "../../../features/step-up/useStepUp";
import { errorReason, useRefreshPayments } from "./api";

type Filter = "pending" | "all";

/** Смена реквизитов контрагента (FX-4): запрос виден бухгалтеру, реквизиты применяются только его подтверждением. */
export function BankChangesPanel() {
  const { t } = useTranslation("payments");
  const { me } = useAuth();
  const [filter, setFilter] = useState<Filter>("pending");
  const list = useListBankChangeRequests(filter === "pending" ? { status: "pending" } : undefined);
  const canDecide = canEdit(me, "eds.payments");
  const [approving, setApproving] = useState<BankChangeItem | null>(null);
  const [rejecting, setRejecting] = useState<BankChangeItem | null>(null);

  let body;
  if (list.isPending) {
    body = <ListSkeleton rows={3} />;
  } else if (list.isError) {
    body = (
      <EmptyState
        title={t("bankChanges.loadError.title")}
        text={t("bankChanges.loadError.text")}
        action={
          <Button
            onClick={() => {
              void list.refetch();
            }}
          >
            {t("state.retry")}
          </Button>
        }
      />
    );
  } else if (list.data.items.length === 0) {
    body = <EmptyState title={t("bankChanges.empty.title")} text={t("bankChanges.empty.text")} />;
  } else {
    body = (
      <ul className="pf-bank-list" aria-label={t("bankChanges.listLabel")}>
        {list.data.items.map((item) => (
          <li key={item.id} className="pf-bank-card">
            <BankChangeRow
              item={item}
              canDecide={canDecide}
              onApprove={() => {
                setApproving(item);
              }}
              onReject={() => {
                setRejecting(item);
              }}
            />
          </li>
        ))}
      </ul>
    );
  }

  return (
    <div>
      <Segmented
        aria-label={t("bankChanges.filterLabel")}
        value={filter}
        options={[
          { value: "pending", label: t("bankChanges.filter.pending") },
          { value: "all", label: t("bankChanges.filter.all") },
        ]}
        onChange={(value) => {
          setFilter(value as Filter);
        }}
      />
      {body}
      {approving ? (
        <ApproveModal
          item={approving}
          onClose={() => {
            setApproving(null);
          }}
        />
      ) : null}
      {rejecting ? (
        <RejectModal
          item={rejecting}
          onClose={() => {
            setRejecting(null);
          }}
        />
      ) : null}
    </div>
  );
}

function BankChangeRow({
  item,
  canDecide,
  onApprove,
  onReject,
}: {
  item: BankChangeItem;
  canDecide: boolean;
  onApprove: () => void;
  onReject: () => void;
}) {
  const { t } = useTranslation("payments");
  const { date } = useFormat();
  const blocked = item.stale || item.company_archived;
  return (
    <>
      <div className="pf-bank-head">
        <strong>{item.company_name}</strong>
        <StatusTag kind="categoryRequest" status={item.status}>
          {t(`bankChanges.status.${item.status}`)}
        </StatusTag>
      </div>
      {item.company_inn ? (
        <div className="pf-bank-sub">{t("bankChanges.inn", { inn: item.company_inn })}</div>
      ) : null}
      <dl className="pf-bank-details">
        <dt>{t("bankChanges.old")}</dt>
        <dd>{item.old_bank_details || t("bankChanges.notSet")}</dd>
        <dt>{t("bankChanges.new")}</dt>
        <dd>
          <strong>{item.new_bank_details || t("bankChanges.notSet")}</strong>
        </dd>
        <dt>{t("bankChanges.requestedBy")}</dt>
        <dd>
          {item.requested_by_name}
          {item.requested_by_email ? ` · ${item.requested_by_email}` : ""}
          {item.requested_ip ? ` · ${item.requested_ip}` : ""}
          {` · ${date(item.created_at, "datetime")}`}
        </dd>
      </dl>
      {item.reject_reason ? (
        <div className="pf-bank-sub">
          {t("bankChanges.rejectReason", { reason: item.reject_reason })}
        </div>
      ) : null}
      {item.company_archived ? (
        <Alert type="warning" showIcon message={t("bankChanges.archived")} />
      ) : item.stale ? (
        <Alert type="warning" showIcon message={t("bankChanges.stale")} />
      ) : null}
      {item.status === "pending" && canDecide ? (
        <div className="pf-bank-actions">
          <Button type="primary" disabled={blocked} onClick={onApprove}>
            {t("bankChanges.approve")}
          </Button>
          <Button onClick={onReject}>{t("bankChanges.reject")}</Button>
        </div>
      ) : null}
    </>
  );
}

function conflictMessage(error: unknown, t: (key: string) => string): string {
  if (error instanceof ApiError && error.status === 409) {
    const reason = errorReason(error);
    if (reason) return t(`bankChanges.conflict.${reason}`);
  }
  return t("bankChanges.conflict.unknown");
}

function useAfterDecision(onClose: () => void) {
  const refresh = useRefreshPayments();
  return () => {
    void refresh();
    onClose();
  };
}

function ApproveModal({ item, onClose }: { item: BankChangeItem; onClose: () => void }) {
  const { t } = useTranslation("payments");
  const done = useAfterDecision(onClose);
  const approve = useApproveBankChangeRequest({ mutation: { onSuccess: done } });
  const stepUp = useStepUp();
  // Подтверждение реквизитов — со свежим кодом второго фактора (ДВ-4б): сервер отказал — окно спрашивает код и повторяет
  const run = () => {
    approve.mutate({ id: item.id }, { onError: (error) => stepUp.ask(error, run) });
  };
  return (
    <Dialog
      open
      title={t("bankChanges.approveModal.title", { name: item.company_name })}
      onCancel={onClose}
      footer={[
        <Button key="cancel" onClick={onClose}>
          {t("bankChanges.cancel")}
        </Button>,
        <Button key="ok" type="primary" loading={approve.isPending} onClick={run}>
          {t("bankChanges.approve")}
        </Button>,
      ]}
    >
      <p>
        <strong>{item.new_bank_details}</strong>
      </p>
      {/* Реестр рисков М1: подмену реквизитов ловит звонок по номеру из своей карточки, а не из запроса */}
      <Alert
        type={item.company_phone ? "info" : "warning"}
        showIcon
        message={
          item.company_phone
            ? t("bankChanges.approveModal.callback", { phone: item.company_phone })
            : t("bankChanges.approveModal.noPhone")
        }
      />
      {approve.isError && !isStepUpError(approve.error) ? (
        <Alert type="error" showIcon role="alert" message={conflictMessage(approve.error, t)} />
      ) : null}
      {stepUp.dialog}
    </Dialog>
  );
}

function RejectModal({ item, onClose }: { item: BankChangeItem; onClose: () => void }) {
  const { t } = useTranslation("payments");
  const done = useAfterDecision(onClose);
  const reject = useRejectBankChangeRequest({ mutation: { onSuccess: done } });
  const [reason, setReason] = useState("");
  const id = useId();
  return (
    <Dialog
      open
      title={t("bankChanges.rejectModal.title", { name: item.company_name })}
      onCancel={onClose}
      footer={[
        <Button key="cancel" onClick={onClose}>
          {t("bankChanges.cancel")}
        </Button>,
        <Button
          key="ok"
          danger
          loading={reject.isPending}
          disabled={!reason.trim()}
          onClick={() => {
            reject.mutate({ id: item.id, data: { reason: reason.trim() } });
          }}
        >
          {t("bankChanges.reject")}
        </Button>,
      ]}
    >
      <FormField id={id} label={t("bankChanges.rejectModal.reason")}>
        <Input.TextArea
          id={id}
          rows={3}
          value={reason}
          maxLength={1000}
          onChange={(event) => {
            setReason(event.target.value);
          }}
        />
      </FormField>
      {reject.isError ? (
        <Alert type="error" showIcon role="alert" message={conflictMessage(reject.error, t)} />
      ) : null}
    </Dialog>
  );
}
