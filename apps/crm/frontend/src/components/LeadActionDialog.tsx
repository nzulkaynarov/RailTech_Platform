import { Alert, Checkbox, DatePicker, Input, InputNumber, Modal, Select } from "antd";
import type { Dayjs } from "dayjs";
import { useState } from "react";

import { useDealOptions } from "../api/dealQueries";
import type { LeadAction } from "../api/queries";
import { groupThousands, parseAmount } from "../domain/deals";
import { defaultSnooze, fromTashkentWall, snoozeDayDisabled } from "../domain/snooze";
import { t } from "../i18n/ru";
import { DATETIME_FORMAT } from "../lib/time";

export type Dialog = "return" | "snooze" | "lost" | "won" | "note";

const TITLES: Record<Dialog, string> = {
  return: t.actions.returnNote,
  snooze: t.actions.snoozeUntil,
  lost: t.actions.lostReason,
  won: t.actions.wonTitle,
  note: t.actions.note,
};
const OK: Record<Dialog, string> = {
  return: t.actions.returnToBot,
  snooze: t.actions.snooze,
  lost: t.actions.lost,
  won: t.actions.won,
  note: t.actions.note,
};

/** Подпись поля ввода (она же placeholder). */
const FIELD: Record<Dialog, string> = {
  ...TITLES,
  won: t.actions.wonNote,
  lost: t.actions.lostComment,
  note: t.actions.noteText,
};

type Extra = {
  forBot: boolean;
  until: Dayjs | null;
  lostReason: string | null;
  amount: number | null;
};

function toAction(dialog: Dialog, text: string, extra: Extra) {
  const { forBot, until, lostReason, amount } = extra;
  const value = text.trim() || null;
  const actions: Record<Dialog, LeadAction | null> = {
    return: { kind: "return", note: value },
    lost: lostReason ? { kind: "lost", reason: value, lostReason } : null,
    won: { kind: "won", reason: value, amount },
    note: { kind: "note", text: text.trim(), visibleToBot: forBot },
    snooze: until ? { kind: "snooze", until: fromTashkentWall(until) } : null,
  };
  return actions[dialog];
}

type Props = {
  dialog: Dialog | null;
  busy: boolean;
  onClose: () => void;
  onRun: (action: LeadAction) => Promise<boolean>;
  /** Последнее сообщение клиента без ответа — предупреждение перед «Вернуть боту». */
  unanswered?: string | null;
};

/**
 * Диалог действия с текстом/датой: заголовок и кнопка — глаголом конкретного действия.
 * Монтируется заново при каждом открытии (`key`), поэтому «Отложить до» считается от
 * момента открытия, а не загрузки страницы.
 */
export function LeadActionDialog({ dialog, busy, onClose, onRun, unanswered }: Props) {
  const [text, setText] = useState("");
  const [forBot, setForBot] = useState(true);
  const [until, setUntil] = useState<Dayjs | null>(() => defaultSnooze(new Date()));
  const [lostReason, setLostReason] = useState<string | null>(null);
  const [amount, setAmount] = useState<number | null>(null);
  const options = useDealOptions().data;
  const submit = async () => {
    const extra = { forBot, until, lostReason, amount };
    const action = dialog ? toAction(dialog, text, extra) : null;
    if (action && (await onRun(action))) setText("");
  };
  return (
    <Modal
      open={dialog !== null}
      title={dialog ? TITLES[dialog] : ""}
      okText={dialog ? OK[dialog] : t.actions.confirm}
      okButtonProps={{
        danger: dialog === "lost",
        disabled: (dialog === "note" && !text.trim()) || (dialog === "lost" && !lostReason),
      }}
      cancelText={t.actions.cancel}
      confirmLoading={busy}
      onOk={() => void submit()}
      onCancel={onClose}
      destroyOnHidden
    >
      {dialog === "return" && unanswered ? (
        <Alert
          type="warning"
          showIcon
          className="dialog-alert"
          message={t.actions.returnUnanswered}
          description={`«${unanswered}»`}
        />
      ) : null}
      {dialog === "lost" ? (
        <Select<string>
          className="dialog-field"
          aria-label={t.actions.lostReasonPick}
          placeholder={t.actions.lostReasonPick}
          value={lostReason}
          onChange={setLostReason}
          options={(options?.lost_reasons ?? []).map((r) => ({ value: r, label: r }))}
          style={{ width: "100%" }}
        />
      ) : null}
      {dialog === "won" ? (
        <InputNumber<number>
          className="dialog-field"
          aria-label={t.actions.wonAmount}
          placeholder={t.actions.wonAmount}
          min={0}
          step={1000}
          value={amount}
          onChange={setAmount}
          formatter={groupThousands}
          parser={parseAmount}
          suffix={options?.currency ?? "UZS"}
          style={{ width: "100%" }}
        />
      ) : null}
      {dialog === "snooze" ? (
        <DatePicker
          showTime
          format={DATETIME_FORMAT}
          aria-label={t.actions.snoozeUntil}
          value={until}
          onChange={setUntil}
          disabledDate={(d) => snoozeDayDisabled(d, new Date())}
          style={{ width: "100%" }}
        />
      ) : (
        <Input.TextArea
          rows={4}
          aria-label={dialog ? FIELD[dialog] : undefined}
          value={text}
          placeholder={dialog ? FIELD[dialog] : ""}
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
