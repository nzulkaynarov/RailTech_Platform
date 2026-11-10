import { Alert, App, Button, Input, Modal } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "../../../shared/api/errors";
import type { InboundMailBulkArchiveResult } from "../../../shared/api/generated/model";
import { bulkArchiveInboundMail } from "../../../shared/api/generated/platform-bff";
import { useRefreshMail } from "./mailModel";

/** Панель «Выбрано N · В архив»: причина одна на всех, подтверждение с «Что произойдёт». */
export function BulkBar({ ids, onClear }: { ids: readonly number[]; onClear: () => void }) {
  const { t } = useTranslation("letters");
  const { message } = App.useApp();
  const refresh = useRefreshMail();
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  /** Итог пачки словами: сколько ушло в архив и почему пропущены остальные (названы все причины). */
  const summary = (result: InboundMailBulkArchiveResult): string => {
    const done = t("mail.bulk.done", { count: result.archived.length });
    if (result.skipped.length === 0) return done;
    const reasons = [
      ...new Set(
        result.skipped.map((s) =>
          t(`mail.bulk.skip.${s.reason}`, { name: s.assignee?.name ?? t("mail.bulk.colleague") }),
        ),
      ),
    ].join("; ");
    return `${done} ${t("mail.bulk.skipped", { count: result.skipped.length, reasons })}`;
  };
  const close = () => {
    setOpen(false);
    setError(null);
  };
  const run = async () => {
    setPending(true);
    setError(null);
    try {
      const result = await bulkArchiveInboundMail({ ids: [...ids], reason: reason.trim() });
      void message.success(summary(result), 6);
      setReason("");
      close();
      onClear();
      await refresh();
    } catch (failure) {
      const text = failure instanceof ApiError ? failure.message : String(failure);
      setError(t("mail.actions.failed", { reason: text }));
    } finally {
      setPending(false);
    }
  };
  return (
    <div className="pf-mail-bulk" role="region" aria-label={t("mail.bulk.label")}>
      <span>{t("mail.bulk.selected", { count: ids.length })}</span>
      <Button
        onClick={() => {
          setOpen(true);
        }}
      >
        {t("mail.bulk.archive")}
      </Button>
      <Button type="link" onClick={onClear}>
        {t("mail.bulk.clear")}
      </Button>
      <Modal
        open={open}
        width={480}
        title={t("mail.bulk.title", { count: ids.length })}
        onCancel={close}
        footer={null}
        destroyOnHidden
      >
        <div className="pf-mail-actions">
          <label htmlFor="mail-bulk-reason">{t("mail.actions.archiveReason")}</label>
          <Input
            id="mail-bulk-reason"
            value={reason}
            maxLength={500}
            placeholder={t("mail.bulk.hint")}
            onChange={(event) => {
              setReason(event.target.value);
            }}
          />
          <div className="pf-fp-row">
            {(["bulk.reasonNewsletter", "bulk.reasonNotice"] as const).map((key) => (
              <Button
                key={key}
                size="small"
                onClick={() => {
                  setReason(t(`mail.${key}`));
                }}
              >
                {t(`mail.${key}`)}
              </Button>
            ))}
          </div>
          {error ? <Alert type="error" showIcon role="alert" message={error} /> : null}
          <div className="pf-fp-row">
            <Button
              type="primary"
              loading={pending}
              disabled={reason.trim().length < 3}
              onClick={() => void run()}
            >
              {t("mail.bulk.confirm")}
            </Button>
            <Button onClick={close}>{t("mail.actions.cancel")}</Button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
