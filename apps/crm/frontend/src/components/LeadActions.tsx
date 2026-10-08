import { App as AntApp, Button, Checkbox, DatePicker, Input, Modal, Space } from "antd";
import dayjs, { type Dayjs } from "dayjs";
import { useState } from "react";

import type { LeadDetail } from "../api/generated/model";
import { ApiError } from "../api/http";
import { type LeadAction, useLeadAction } from "../api/queries";
import { errorText, t } from "../i18n/ru";
import { type ActionRights, availableActions } from "./leadActionRules";
import { MakeCustomer } from "./MakeCustomer";

type Dialog = "return" | "snooze" | "lost" | "won" | "note" | null;

export function LeadActions({ lead, rights }: { lead: LeadDetail; rights: ActionRights }) {
  const { message } = AntApp.useApp();
  const mutation = useLeadAction(lead.id);
  const [dialog, setDialog] = useState<Dialog>(null);
  const [text, setText] = useState("");
  const [forBot, setForBot] = useState(true);
  const [until, setUntil] = useState<Dayjs | null>(dayjs().add(2, "hour"));
  const show = availableActions(lead, rights);

  const run = async (action: LeadAction) => {
    try {
      await mutation.mutateAsync(action);
      void message.success(t.actions.done);
      setDialog(null);
      setText("");
    } catch (error) {
      void message.error(errorText((error as ApiError).code, (error as Error).message));
    }
  };

  const confirm = () => {
    const value = text.trim() || null;
    if (dialog === "return") return run({ kind: "return", note: value });
    if (dialog === "lost") return run({ kind: "lost", reason: value });
    if (dialog === "won") return run({ kind: "won", reason: value });
    if (dialog === "note") return run({ kind: "note", text: text.trim(), visibleToBot: forBot });
    if (dialog === "snooze" && until) return run({ kind: "snooze", until: until.toISOString() });
    return undefined;
  };

  return (
    <>
      <Space wrap>
        {show.take ? (
          <Button
            type="primary"
            loading={mutation.isPending}
            onClick={() => void run({ kind: "take" })}
          >
            {t.actions.take}
          </Button>
        ) : null}
        {show.returnToBot ? (
          <Button
            onClick={() => {
              setDialog("return");
            }}
          >
            {t.actions.returnToBot}
          </Button>
        ) : null}
        {show.snooze ? (
          <Button
            onClick={() => {
              setDialog("snooze");
            }}
          >
            {t.actions.snooze}
          </Button>
        ) : null}
        {show.close ? (
          <Button
            onClick={() => {
              setDialog("won");
            }}
          >
            {t.actions.won}
          </Button>
        ) : null}
        {show.close ? (
          <Button
            danger
            onClick={() => {
              setDialog("lost");
            }}
          >
            {t.actions.lost}
          </Button>
        ) : null}
        {show.makeCustomer ? <MakeCustomer leadId={lead.id} /> : null}
        {show.note ? (
          <Button
            onClick={() => {
              setDialog("note");
            }}
          >
            {t.actions.note}
          </Button>
        ) : null}
      </Space>
      <Modal
        open={dialog !== null}
        title={dialogTitle(dialog)}
        okText={t.actions.confirm}
        cancelText={t.actions.cancel}
        confirmLoading={mutation.isPending}
        onOk={() => void confirm()}
        onCancel={() => {
          setDialog(null);
        }}
        destroyOnHidden
      >
        {dialog === "snooze" ? (
          <DatePicker showTime value={until} onChange={setUntil} style={{ width: "100%" }} />
        ) : (
          <Input.TextArea
            rows={4}
            value={text}
            placeholder={dialogTitle(dialog)}
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
    </>
  );
}

function dialogTitle(dialog: Dialog): string {
  switch (dialog) {
    case "return":
      return t.actions.returnNote;
    case "snooze":
      return t.actions.snoozeUntil;
    case "lost":
      return t.actions.lostReason;
    case "won":
      return t.actions.won;
    case "note":
      return t.actions.noteText;
    default:
      return "";
  }
}
