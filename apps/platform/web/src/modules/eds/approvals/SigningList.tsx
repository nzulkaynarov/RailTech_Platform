import { App, Button, Card, Input } from "antd";
import { Dialog } from "../../../shared/ui/Dialog";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type { SigningApprovalRow } from "../../../shared/api/generated/model";
import {
  useDecideSigningApproval,
  useListSigningApprovals,
} from "../../../shared/api/generated/platform-bff";
import { useFormat } from "../../../shared/lib/useFormat";
import { useConfirmAction } from "../../../shared/ui/useConfirmAction";
import { reasonText } from "../documents/errors";
import { useRefreshSigning } from "../refreshKeys";

/** Документы ERP, ждущие подписи текущего сотрудника (SIGN-4): «Подписать» или «Отказать» с причиной. */
export function SigningList({ focusId = null }: { focusId?: string | null }) {
  const { t } = useTranslation("approvals");
  const { money } = useFormat();
  const confirmAction = useConfirmAction();
  const { message } = App.useApp();
  const list = useListSigningApprovals();
  const refresh = useRefreshSigning();
  const [rejecting, setRejecting] = useState<SigningApprovalRow | null>(null);
  const [reason, setReason] = useState("");
  const decide = useDecideSigningApproval({
    mutation: {
      onSuccess: () => {
        setRejecting(null);
        setReason("");
        void refresh();
        void message.success(t("signing.done"));
      },
      onError: (failure) => {
        void message.error(t("signing.failedReason", { reason: reasonText(t, failure) }));
      },
    },
  });
  const items = list.data?.items ?? [];
  const focused = useRef<HTMLLIElement | null>(null);
  const hasFocus = focusId !== null && items.some((row) => row.id === focusId);
  // Строка «Подписать …» очереди ведёт сюда: нужный шаг выделен и показан (СЦ-9)
  useEffect(() => {
    // в jsdom `scrollIntoView` нет
    // eslint-disable-next-line @typescript-eslint/no-unnecessary-condition
    if (hasFocus) focused.current?.scrollIntoView?.({ block: "center" });
  }, [hasFocus]);
  if (items.length === 0) return null;

  return (
    <Card title={t("signing.title")} className="pf-signing-list">
      <ul className="pf-dec-cards" aria-label={t("signing.title")}>
        {items.map((row) => (
          <li
            key={row.id}
            ref={row.id === focusId ? focused : undefined}
            data-selected={row.id === focusId ? "true" : undefined}
            aria-current={row.id === focusId ? "true" : undefined}
          >
            <div className="pf-dec-card-head">
              <strong>{row.title}</strong>
              <span className="pf-hint">
                {[row.step, row.amount ? money(row.amount, { currency: row.currency }) : null]
                  .filter(Boolean)
                  .join(" · ")}
              </span>
            </div>
            <div className="pf-dec-card-actions">
              <Button
                type="primary"
                size="small"
                loading={decide.isPending}
                onClick={() => {
                  confirmAction({
                    action: row.action === "visa" ? t("signing.approve") : t("signing.sign"),
                    object: row.title,
                    onConfirm: () => {
                      decide.mutate({ id: row.id, data: { decision: "approve" } });
                    },
                  });
                }}
              >
                {row.action === "visa" ? t("signing.approve") : t("signing.sign")}
              </Button>
              <Button
                size="small"
                onClick={() => {
                  setRejecting(row);
                }}
              >
                {row.action === "visa" ? t("signing.return") : t("signing.reject")}
              </Button>
            </div>
          </li>
        ))}
      </ul>
      <Dialog
        open={rejecting !== null}
        title={rejecting?.action === "visa" ? t("signing.returnTitle") : t("signing.rejectTitle")}
        okLabel={rejecting?.action === "visa" ? t("signing.return") : t("signing.reject")}
        okDisabled={!reason.trim()}
        loading={decide.isPending}
        onCancel={() => {
          setRejecting(null);
        }}
        onOk={() => {
          if (rejecting)
            decide.mutate({
              id: rejecting.id,
              data: {
                decision: rejecting.action === "visa" ? "return" : "reject",
                comment: reason.trim(),
              },
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
      </Dialog>
    </Card>
  );
}
