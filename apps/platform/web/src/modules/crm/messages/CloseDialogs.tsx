import { Input, Select } from "antd";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  useCloseCrmLead,
  useDiscardCrmLead,
  useGetCrmCloseOptions,
  useListCrmLeads,
} from "../../../shared/api/generated/platform-bff";
import { Dialog } from "../../../shared/ui/Dialog";
import { ErrorNote, FormField } from "../../../shared/ui/FormParts";
import { useRefreshMessages } from "./actions";
import { actionError } from "./labels";

import "./messages.css";

export type DiscardKind = "spam" | "test" | "duplicate";
export type CloseKind = "won" | "lost" | DiscardKind;

/**
 * «Заключено» и «Отказ» (LH-1): одно окно с одним подтверждением. Отказ без причины из справочника «Настроек» не
 * уходит; комментарий — в заметку команды. Итог показывает сам экран после обновления, не всплывающее сообщение.
 */
export function OutcomeDialog({
  lead,
  outcome,
  onClose,
}: {
  lead: string;
  outcome: "won" | "lost";
  onClose: () => void;
}) {
  const { t } = useTranslation("messages");
  const refresh = useRefreshMessages();
  const ids = { reason: useId(), comment: useId() };
  const options = useGetCrmCloseOptions();
  const [reason, setReason] = useState<string | null>(null);
  const [comment, setComment] = useState("");
  const [touched, setTouched] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const close = useCloseCrmLead({
    mutation: {
      onSuccess: () => {
        refresh();
        onClose();
      },
      onError: (error) => {
        setFailure(actionError(t, error));
      },
    },
  });
  const lost = outcome === "lost";
  const reasonMissing = lost && !reason;
  const wonByErp = outcome === "won" && options.data?.won_by_erp === true;
  const submit = () => {
    setTouched(true);
    if (reasonMissing || wonByErp) return;
    setFailure(null);
    close.mutate({
      lead,
      data: { outcome, lost_reason: lost ? reason : null, reason: comment.trim() || null },
    });
  };
  return (
    <Dialog
      open
      title={t(lost ? "close.lostTitle" : "close.wonTitle")}
      okLabel={t(lost ? "close.lostSubmit" : "close.wonSubmit")}
      okDisabled={wonByErp}
      loading={close.isPending}
      onOk={submit}
      onCancel={onClose}
    >
      <div className="pf-msg-handover">
        {wonByErp ? <p className="pf-hint">{t("close.wonByErp")}</p> : null}
        {lost ? (
          <FormField
            id={ids.reason}
            label={t("close.reason")}
            hint={
              touched && reasonMissing
                ? t("close.reasonRequired")
                : options.isError
                  ? t("close.optionsFailed")
                  : undefined
            }
          >
            <Select
              id={ids.reason}
              status={touched && reasonMissing ? "error" : undefined}
              loading={options.isPending}
              placeholder={t("close.reasonPlaceholder")}
              value={reason}
              onChange={(value: string) => {
                setReason(value);
              }}
              options={(options.data?.lost_reasons ?? []).map((value) => ({ value, label: value }))}
              style={{ width: "100%" }}
            />
          </FormField>
        ) : null}
        <FormField id={ids.comment} label={t("close.comment")}>
          <Input.TextArea
            id={ids.comment}
            rows={3}
            maxLength={1000}
            value={comment}
            onChange={(event) => {
              setComment(event.target.value);
            }}
          />
        </FormField>
        <ErrorNote message={failure} />
      </div>
    </Dialog>
  );
}

/**
 * «Спам», «Тест», «Дубль» (LH-1): одно подтверждение. «Тест» стирает данные лида без возврата — об этом сказано в окне;
 * «Дубль» просит выбрать лид, который остаётся (ссылка, без склейки).
 */
export function DiscardDialog({
  lead,
  kind,
  onClose,
}: {
  lead: string;
  kind: DiscardKind;
  onClose: () => void;
}) {
  const { t } = useTranslation("messages");
  const refresh = useRefreshMessages();
  const pick = useId();
  const [search, setSearch] = useState("");
  const [target, setTarget] = useState<string | null>(null);
  const [touched, setTouched] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const duplicate = kind === "duplicate";
  const found = useListCrmLeads(
    { q: search.trim() || undefined, limit: 10 },
    { query: { enabled: duplicate && search.trim().length >= 2 } },
  );
  const discard = useDiscardCrmLead({
    mutation: {
      onSuccess: () => {
        refresh();
        onClose();
      },
      onError: (error) => {
        setFailure(actionError(t, error));
      },
    },
  });
  const targetMissing = duplicate && !target;
  const submit = () => {
    setTouched(true);
    if (targetMissing) return;
    setFailure(null);
    discard.mutate({ lead, data: { kind, duplicate_of: duplicate ? target : null } });
  };
  const items = (found.data?.items ?? []).filter((item) => item.lead !== lead);
  return (
    <Dialog
      open
      title={t(`discard.${kind}.title`)}
      okLabel={t(`discard.${kind}.submit`)}
      danger={kind === "test"}
      loading={discard.isPending}
      onOk={submit}
      onCancel={onClose}
    >
      <div className="pf-msg-handover">
        <p className="pf-hint">{t(`discard.${kind}.text`)}</p>
        {duplicate ? (
          <FormField
            id={pick}
            label={t("discard.duplicate.pick")}
            hint={touched && targetMissing ? t("discard.duplicate.required") : undefined}
          >
            <Select
              id={pick}
              showSearch
              filterOption={false}
              status={touched && targetMissing ? "error" : undefined}
              loading={found.isFetching}
              placeholder={t("discard.duplicate.placeholder")}
              notFoundContent={
                search.trim().length < 2 ? t("discard.duplicate.hint") : t("discard.duplicate.none")
              }
              value={target}
              onSearch={setSearch}
              onChange={(value: string) => {
                setTarget(value);
              }}
              options={items.map((item) => ({
                value: item.lead,
                label: `${item.name} · ${item.lead}`,
              }))}
              style={{ width: "100%" }}
            />
          </FormField>
        ) : null}
        <ErrorNote message={failure} />
      </div>
    </Dialog>
  );
}

/** Окно по пункту меню «Закрыть»: исход сделки или «Спам», «Тест», «Дубль». */
export function CloseDialog({
  lead,
  kind,
  onClose,
}: {
  lead: string;
  kind: CloseKind;
  onClose: () => void;
}) {
  return kind === "won" || kind === "lost" ? (
    <OutcomeDialog lead={lead} outcome={kind} onClose={onClose} />
  ) : (
    <DiscardDialog lead={lead} kind={kind} onClose={onClose} />
  );
}
