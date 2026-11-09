import { App, Button, Card, Input, Modal } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { SigningApprovalRow } from "../../../shared/api/generated/model";
import {
  useDecideSigningApproval,
  useListSigningApprovals,
} from "../../../shared/api/generated/platform-bff";

/** Документы ERP, ждущие подписи текущего сотрудника (SIGN-4): «Подписать» или «Отказать» с причиной. */
export function SigningList() {
  const { t } = useTranslation("approvals");
  const { message } = App.useApp();
  const list = useListSigningApprovals();
  const [rejecting, setRejecting] = useState<SigningApprovalRow | null>(null);
  const [reason, setReason] = useState("");
  const decide = useDecideSigningApproval({
    mutation: {
      onSuccess: () => {
        setRejecting(null);
        setReason("");
        void list.refetch();
        void message.success(t("signing.done"));
      },
      onError: () => {
        void message.error(t("signing.failed"));
      },
    },
  });
  const items = list.data?.items ?? [];
  if (items.length === 0) return null;

  return (
    <Card title={t("signing.title")} className="pf-signing-list">
      <ul className="pf-dec-cards" aria-label={t("signing.title")}>
        {items.map((row) => (
          <li key={row.id}>
            <div className="pf-dec-card-head">
              <strong>{row.title}</strong>
              <span className="pf-hint">
                {row.amount ? `${row.amount} ${row.currency ?? ""}` : null}
              </span>
            </div>
            <div className="pf-dec-card-actions">
              <Button
                type="primary"
                size="small"
                loading={decide.isPending}
                onClick={() => {
                  decide.mutate({ id: row.id, data: { decision: "approve" } });
                }}
              >
                {t("signing.sign")}
              </Button>
              <Button
                size="small"
                onClick={() => {
                  setRejecting(row);
                }}
              >
                {t("signing.reject")}
              </Button>
            </div>
          </li>
        ))}
      </ul>
      <Modal
        open={rejecting !== null}
        title={t("signing.rejectTitle")}
        okText={t("signing.reject")}
        okButtonProps={{ disabled: !reason.trim(), loading: decide.isPending }}
        onCancel={() => {
          setRejecting(null);
        }}
        onOk={() => {
          if (rejecting)
            decide.mutate({
              id: rejecting.id,
              data: { decision: "reject", comment: reason.trim() },
            });
        }}
      >
        <Input.TextArea
          aria-label={t("signing.reason")}
          placeholder={t("signing.reason")}
          value={reason}
          maxLength={4000}
          rows={3}
          onChange={(event) => {
            setReason(event.target.value);
          }}
        />
      </Modal>
    </Card>
  );
}
