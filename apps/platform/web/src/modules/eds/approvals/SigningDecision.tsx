import { App, Button, Input } from "antd";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  useDecideSigningApproval,
  useListSigningApprovals,
} from "../../../shared/api/generated/platform-bff";
import { useFormat } from "../../../shared/lib/useFormat";
import { Dialog } from "../../../shared/ui/Dialog";
import { useConfirmAction } from "../../../shared/ui/useConfirmAction";
import { reasonText } from "../documents/errors";
import { useRefreshSigning } from "../refreshKeys";

/**
 * Решение по подписи или визе документа ERP (SIGN-4, ГЛ-1): строка «Подписать …» / «Завизировать …» очереди открывает это окно
 * по адресу `/dashboard/queue?signing=<маршрут>`. «Подписать» или «Согласовать» — с подтверждением (необратимо); «Отказать» или
 * «Вернуть с замечанием» — с причиной, её увидит автор. Шага уже нет в списке (решили без вас) — окно закрывается само.
 */
export function SigningDecision({ id, onClose }: { id: string | null; onClose: () => void }) {
  const { t } = useTranslation("approvals");
  const { money } = useFormat();
  const confirmAction = useConfirmAction();
  const { message } = App.useApp();
  const list = useListSigningApprovals({ query: { enabled: id !== null } });
  const refresh = useRefreshSigning();
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");
  const row = id === null ? undefined : list.data?.items.find((item) => item.id === id);
  const close = () => {
    setRejecting(false);
    setReason("");
    onClose();
  };
  const decide = useDecideSigningApproval({
    mutation: {
      onSuccess: () => {
        close();
        void refresh();
        void message.success(t("signing.done"));
      },
      onError: (failure) => {
        void message.error(t("signing.failedReason", { reason: reasonText(t, failure) }));
      },
    },
  });
  // Шаг уже решён: список ответил, а нашего маршрута в нём нет
  const gone = id !== null && list.data !== undefined && row === undefined;
  useEffect(() => {
    if (gone) onClose();
  }, [gone, onClose]);
  if (id === null || row === undefined) return null;
  const visa = row.action === "visa";
  const yes = visa ? t("signing.approve") : t("signing.sign");
  const no = visa ? t("signing.return") : t("signing.reject");
  const hint = [row.step, row.amount ? money(row.amount, { currency: row.currency }) : null]
    .filter(Boolean)
    .join(" · ");

  if (rejecting) {
    return (
      <Dialog
        open
        title={visa ? t("signing.returnTitle") : t("signing.rejectTitle")}
        okLabel={no}
        okDisabled={!reason.trim()}
        loading={decide.isPending}
        danger={!visa}
        onCancel={close}
        onOk={() => {
          decide.mutate({
            id: row.id,
            data: { decision: visa ? "return" : "reject", comment: reason.trim() },
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
    );
  }
  return (
    <Dialog
      open
      title={row.title}
      onCancel={close}
      footer={
        <>
          <Button
            onClick={() => {
              setRejecting(true);
            }}
          >
            {no}
          </Button>
          <Button
            type="primary"
            loading={decide.isPending}
            onClick={() => {
              confirmAction({
                action: yes,
                object: row.title,
                onConfirm: () => {
                  decide.mutate({ id: row.id, data: { decision: "approve" } });
                },
              });
            }}
          >
            {yes}
          </Button>
        </>
      }
    >
      <p className="pf-hint">{hint}</p>
    </Dialog>
  );
}
