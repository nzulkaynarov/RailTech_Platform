import { Alert, App, Button, Dropdown, Input, Modal, Select } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { useAuth } from "../../../app/auth/useAuth";
import { ApiError } from "../../../shared/api/errors";
import type { LetterCard, LetterInstruction } from "../../../shared/api/generated/model";
import {
  closeLetterWithoutReply,
  reopenLetter,
  returnInstructionToAuthor,
  useListDictionaryItems,
} from "../../../shared/api/generated/platform-bff";
import { localName } from "../dictionaries";
import { useRefreshLetters } from "../inbox/api";

const CLOSE_REASONS = "close-reasons";

function errorText(failure: unknown, fallback: string): string {
  return failure instanceof ApiError ? failure.message || fallback : fallback;
}

/** Название причины закрытия на языке сотрудника; нет в справочнике — код. */
function useReasonName(): (code: string | null | undefined) => string {
  const { i18n } = useTranslation();
  const reasons = useListDictionaryItems(CLOSE_REASONS, undefined, {
    query: { staleTime: 60_000 },
  });
  return (code) => {
    if (!code) return "";
    const item = reasons.data?.items.find((r) => r.code === code);
    return item ? localName(item.name, i18n.language) : code;
  };
}

/** Окно «Закрыть без ответа»: причина из справочника, пояснение — если причина его требует. */
function CloseDialog({ letter, onClose }: { letter: LetterCard; onClose: () => void }) {
  const { t, i18n } = useTranslation("letters");
  const { message } = App.useApp();
  const refresh = useRefreshLetters();
  const reasons = useListDictionaryItems(CLOSE_REASONS, undefined, {
    query: { staleTime: 60_000 },
  });
  const [reason, setReason] = useState<string | undefined>();
  const [comment, setComment] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const picked = reasons.data?.items.find((r) => r.code === reason);
  const needComment = picked?.attrs["comment_required"] === true;
  const run = async () => {
    if (!reason) return;
    setPending(true);
    setError(null);
    try {
      await closeLetterWithoutReply(letter.id, { reason, comment: comment.trim() || null });
      void message.success(t("outcome.close.done", { number: letter.number }));
      onClose();
      await refresh();
    } catch (failure) {
      setError(errorText(failure, t("outcome.failed")));
    } finally {
      setPending(false);
    }
  };
  return (
    <Modal
      open
      width={480}
      title={t("outcome.close.title", { number: letter.number })}
      onCancel={onClose}
      footer={null}
      destroyOnHidden
    >
      <div className="pf-mail-actions">
        <label htmlFor="close-reason">{t("outcome.close.reason")}</label>
        <Select
          id="close-reason"
          value={reason}
          loading={reasons.isPending}
          options={(reasons.data?.items ?? [])
            .filter((r) => r.active)
            .map((r) => ({ value: r.code, label: localName(r.name, i18n.language) }))}
          onChange={(value: string) => {
            setReason(value);
          }}
        />
        <label htmlFor="close-comment">
          {needComment ? t("outcome.close.commentRequired") : t("outcome.close.comment")}
        </label>
        <Input.TextArea
          id="close-comment"
          rows={3}
          maxLength={2000}
          value={comment}
          aria-required={needComment || undefined}
          onChange={(event) => {
            setComment(event.target.value);
          }}
        />
        {error ? <Alert type="error" showIcon role="alert" message={error} /> : null}
        <div className="pf-fp-row">
          <Button
            type="primary"
            loading={pending}
            disabled={!reason || (needComment && !comment.trim())}
            onClick={() => void run()}
          >
            {t("outcome.close.submit")}
          </Button>
          <Button onClick={onClose}>{t("outcome.cancel")}</Button>
        </div>
      </div>
    </Modal>
  );
}

/** Окно «Вернуть автору резолюции»: причина обязательна. */
function ReturnDialog({
  letter,
  instruction,
  onClose,
}: {
  letter: LetterCard;
  instruction: LetterInstruction;
  onClose: () => void;
}) {
  const { t } = useTranslation("letters");
  const { message } = App.useApp();
  const refresh = useRefreshLetters();
  const [reason, setReason] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = async () => {
    setPending(true);
    setError(null);
    try {
      await returnInstructionToAuthor(instruction.id, { reason: reason.trim() });
      void message.success(t("outcome.return.done", { number: letter.number }));
      onClose();
      await refresh();
    } catch (failure) {
      setError(errorText(failure, t("outcome.failed")));
    } finally {
      setPending(false);
    }
  };
  return (
    <Modal
      open
      width={480}
      title={t("outcome.return.title", { number: letter.number })}
      onCancel={onClose}
      footer={null}
      destroyOnHidden
    >
      <div className="pf-mail-actions">
        <label htmlFor="return-reason">{t("outcome.return.reason")}</label>
        <Input.TextArea
          id="return-reason"
          rows={3}
          maxLength={4000}
          value={reason}
          aria-required
          onChange={(event) => {
            setReason(event.target.value);
          }}
        />
        {error ? <Alert type="error" showIcon role="alert" message={error} /> : null}
        <div className="pf-fp-row">
          <Button
            type="primary"
            loading={pending}
            disabled={!reason.trim()}
            onClick={() => void run()}
          >
            {t("outcome.return.submit")}
          </Button>
          <Button onClick={onClose}>{t("outcome.cancel")}</Button>
        </div>
      </div>
    </Modal>
  );
}

/**
 * «Ещё» у поручения ответственного (решение владельца 2026-11-11): «Закрыть без ответа» и «Вернуть автору».
 * Соисполнителю исход письма не положен — меню нет.
 */
export function OutcomeMenu({
  letter,
  instruction,
}: {
  letter: LetterCard;
  instruction: LetterInstruction;
}) {
  const { t } = useTranslation("letters");
  const [open, setOpen] = useState<"close" | "return" | null>(null);
  if (instruction.role !== "responsible" || instruction.status !== "in_work") return null;
  const someoneDone = (letter.instructions ?? []).some((i) => i.status === "executed");
  return (
    <>
      <Dropdown
        trigger={["click"]}
        menu={{
          items: [
            { key: "close", label: t("outcome.close.action") },
            { key: "return", label: t("outcome.return.action"), disabled: someoneDone },
          ],
          onClick: ({ key }) => {
            setOpen(key === "close" ? "close" : "return");
          },
        }}
      >
        <Button>{t("outcome.more")}</Button>
      </Dropdown>
      {open === "close" ? (
        <CloseDialog
          letter={letter}
          onClose={() => {
            setOpen(null);
          }}
        />
      ) : null}
      {open === "return" ? (
        <ReturnDialog
          letter={letter}
          instruction={instruction}
          onClose={() => {
            setOpen(null);
          }}
        />
      ) : null}
    </>
  );
}

/** Плашка закрытого без ответа письма: причина и пояснение; автору резолюции — «Вернуть в работу». */
export function ClosedBanner({ letter }: { letter: LetterCard }) {
  const { t } = useTranslation("letters");
  const { me } = useAuth();
  const { message } = App.useApp();
  const refresh = useRefreshLetters();
  const reasonName = useReasonName();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (letter.status !== "closed") return null;
  const author = letter.office_resolution?.decided_by.id === me.id;
  const reopen = async () => {
    setPending(true);
    setError(null);
    try {
      await reopenLetter(letter.id);
      void message.success(t("outcome.reopen.done", { number: letter.number }));
      await refresh();
    } catch (failure) {
      setError(errorText(failure, t("outcome.failed")));
    } finally {
      setPending(false);
    }
  };
  return (
    <Alert
      type="info"
      showIcon
      role="status"
      message={t("outcome.closedBanner", { reason: reasonName(letter.close_reason) })}
      description={
        <>
          {letter.close_comment ? <p>{letter.close_comment}</p> : null}
          {error ? <Alert type="error" showIcon role="alert" message={error} /> : null}
          {author ? (
            <Button loading={pending} onClick={() => void reopen()}>
              {t("outcome.reopen.action")}
            </Button>
          ) : null}
        </>
      }
    />
  );
}
