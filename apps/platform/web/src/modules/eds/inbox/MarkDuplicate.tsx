import { Alert, App, Button, Checkbox, Input, Modal } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { ApiError } from "../../../shared/api/errors";
import type { LetterCard } from "../../../shared/api/generated/model";
import { markLetterDuplicate } from "../../../shared/api/generated/platform-bff";
import { useRefreshLetters } from "./api";

const OPEN = new Set(["awaiting_resolution", "returned"]);

/** Плашка закрытого дубля (EDS-DUP): ссылка на оригинал. */
export function DuplicateBanner({ letter }: { letter: LetterCard }) {
  const { t } = useTranslation("letters");
  if (letter.status !== "duplicate") return null;
  const original = letter.duplicate_of;
  return (
    <Alert
      type="info"
      showIcon
      role="status"
      message={
        original ? (
          <>
            {t("card.dup.banner")}{" "}
            <Link className="pf-focusable" to={original.path}>
              {original.number}
            </Link>
          </>
        ) : (
          t("card.dup.bannerNoLink")
        )
      }
      description={t("card.dup.bannerText")}
    />
  );
}

/**
 * «Это дубль ВХ-…» (EDS-DUP, ГОСТ Р 7.0.97: документ регистрируется один раз) — у делопроизводителя: письмо закрывается
 * со ссылкой на оригинал, поручения и ознакомления отменяются, номер не освобождается. Резолюция уже есть — подтверждение.
 */
export function MarkDuplicateAction({ letter }: { letter: LetterCard }) {
  const { t } = useTranslation("letters");
  const { message } = App.useApp();
  const refresh = useRefreshLetters();
  const [open, setOpen] = useState(false);
  const [number, setNumber] = useState("");
  const [comment, setComment] = useState("");
  const [confirm, setConfirm] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [needConfirm, setNeedConfirm] = useState(!OPEN.has(letter.status));
  if (letter.status === "duplicate") return null;
  const work = (letter.instructions ?? []).filter((i) => i.status === "in_work").length;
  const close = () => {
    setOpen(false);
    setError(null);
  };
  const run = async () => {
    setPending(true);
    setError(null);
    try {
      await markLetterDuplicate(letter.id, {
        original_number: number.trim(),
        comment: comment.trim() || null,
        confirm,
      });
      void message.success(t("card.dup.done", { number: number.trim() }));
      close();
      await refresh();
    } catch (failure) {
      if (failure instanceof ApiError && failure.details["reason"] === "resolution_exists") {
        setNeedConfirm(true);
      }
      const reason = failure instanceof ApiError ? failure.details["reason"] : undefined;
      setError(
        typeof reason === "string"
          ? t(`card.dup.errors.${reason}`, {
              defaultValue: failure instanceof ApiError ? failure.message : String(failure),
            })
          : failure instanceof ApiError
            ? failure.message
            : String(failure),
      );
    } finally {
      setPending(false);
    }
  };
  return (
    <>
      <Button
        onClick={() => {
          setOpen(true);
        }}
      >
        {t("card.dup.action")}
      </Button>
      <Modal
        open={open}
        width={480}
        title={t("card.dup.title", { number: letter.number })}
        onCancel={close}
        footer={null}
        destroyOnHidden
      >
        <div className="pf-mail-actions">
          <label htmlFor="dup-original">{t("card.dup.original")}</label>
          <Input
            id="dup-original"
            value={number}
            maxLength={32}
            placeholder="ВХ-101/26"
            autoComplete="off"
            onChange={(event) => {
              setNumber(event.target.value);
            }}
          />
          <label htmlFor="dup-comment">{t("card.dup.comment")}</label>
          <Input
            id="dup-comment"
            value={comment}
            maxLength={2000}
            autoComplete="off"
            onChange={(event) => {
              setComment(event.target.value);
            }}
          />
          {needConfirm ? (
            <Checkbox
              checked={confirm}
              onChange={(event) => {
                setConfirm(event.target.checked);
              }}
            >
              {t("card.dup.confirm", { count: work })}
            </Checkbox>
          ) : null}
          {error ? <Alert type="error" showIcon role="alert" message={error} /> : null}
          <div className="pf-fp-row">
            <Button
              type="primary"
              danger
              loading={pending}
              disabled={!number.trim() || (needConfirm && !confirm)}
              onClick={() => void run()}
            >
              {t("card.dup.submit")}
            </Button>
            <Button onClick={close}>{t("card.dup.cancel")}</Button>
          </div>
        </div>
      </Modal>
    </>
  );
}
