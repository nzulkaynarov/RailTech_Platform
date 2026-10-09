import { Checkbox, DatePicker, Input, Modal, Typography } from "antd";
import dayjs, { type Dayjs } from "dayjs";
import { useState } from "react";

import type { LeadAction } from "../api/queries";
import { t } from "../i18n/ru";

export type Dialog = "return" | "snooze" | "lost" | "won" | "note";

const TITLES: Record<Dialog, string> = {
  return: t.actions.returnNote,
  snooze: t.actions.snoozeUntil,
  lost: t.actions.lostReason,
  won: t.actions.wonTitle,
  note: t.actions.noteText,
};
const OK: Record<Dialog, string> = {
  return: t.actions.returnToBot,
  snooze: t.actions.snooze,
  lost: t.actions.lost,
  won: t.actions.won,
  note: t.common.save,
};

function toAction(dialog: Dialog, text: string, forBot: boolean, until: Dayjs | null) {
  const value = text.trim() || null;
  const actions: Record<Dialog, LeadAction | null> = {
    return: { kind: "return", note: value },
    lost: { kind: "lost", reason: value },
    won: { kind: "won", reason: value },
    note: { kind: "note", text: text.trim(), visibleToBot: forBot },
    snooze: until ? { kind: "snooze", until: until.toISOString() } : null,
  };
  return actions[dialog];
}

type Props = {
  dialog: Dialog | null;
  busy: boolean;
  onClose: () => void;
  onRun: (action: LeadAction) => Promise<boolean>;
};

/** Диалог действия с текстом/датой: заголовок и кнопка — глаголом конкретного действия. */
export function LeadActionDialog({ dialog, busy, onClose, onRun }: Props) {
  const [text, setText] = useState("");
  const [forBot, setForBot] = useState(true);
  const [until, setUntil] = useState<Dayjs | null>(dayjs().add(2, "hour"));
  const submit = async () => {
    const action = dialog ? toAction(dialog, text, forBot, until) : null;
    if (action && (await onRun(action))) setText("");
  };
  return (
    <Modal
      open={dialog !== null}
      title={dialog ? TITLES[dialog] : ""}
      okText={dialog ? OK[dialog] : t.actions.confirm}
      okButtonProps={{ danger: dialog === "lost", disabled: dialog === "note" && !text.trim() }}
      cancelText={t.actions.cancel}
      confirmLoading={busy}
      onOk={() => void submit()}
      onCancel={onClose}
      destroyOnHidden
    >
      {dialog === "won" ? (
        <Typography.Paragraph type="secondary">{t.actions.wonNote}</Typography.Paragraph>
      ) : null}
      {dialog === "snooze" ? (
        <DatePicker
          showTime
          format="DD.MM.YYYY HH:mm"
          value={until}
          onChange={setUntil}
          disabledDate={(d) => d.isBefore(dayjs(), "day") || d.isAfter(dayjs().add(7, "day"))}
          style={{ width: "100%" }}
        />
      ) : (
        <Input.TextArea
          rows={4}
          value={text}
          placeholder={dialog === "won" ? t.actions.wonNote : dialog ? TITLES[dialog] : ""}
          onChange={(e) => {
            setText(e.target.value);
          }}
        />
      )}
      {dialog === "note" ? (
        <Checkbox
          checked={forBot}
          onChange={(e) => {
            setForBot(e.target.checked);
          }}
        >
          {t.actions.noteForBot}
        </Checkbox>
      ) : null}
    </Modal>
  );
}
