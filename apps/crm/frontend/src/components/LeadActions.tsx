import { App as AntApp, Button, Space, Tooltip } from "antd";
import type { ReactNode } from "react";
import { useState } from "react";

import type { LeadDetail } from "../api/generated/model";
import type { ApiError } from "../api/http";
import { type LeadAction, useLeadAction } from "../api/queries";
import { ownerModeLabel } from "../domain/labels";
import { useConfirmDanger } from "../hooks/useConfirmDanger";
import { errorText, t } from "../i18n/ru";
import { AssignLead } from "./AssignLead";
import { type Dialog, LeadActionDialog } from "./LeadActionDialog";
import {
  type ActionRights,
  type ActionState,
  isTakeover,
  leadActionStates,
} from "./leadActionRules";
import { MakeCustomer } from "./MakeCustomer";

type ButtonProps = {
  state: ActionState;
  onClick: () => void;
  children: ReactNode;
  primary?: boolean;
  danger?: boolean;
  loading?: boolean;
};

/** Кнопка действия: недоступное показывается неактивным с причиной во всплывающей подсказке. */
function ActionButton({ state, onClick, children, primary, danger, loading }: ButtonProps) {
  if (!state.visible) return null;
  const button = (
    <Button
      type={primary ? "primary" : "default"}
      danger={danger ?? false}
      loading={loading ?? false}
      disabled={Boolean(state.reason)}
      onClick={onClick}
    >
      {children}
    </Button>
  );
  return state.reason ? <Tooltip title={state.reason}>{button}</Tooltip> : button;
}

export function LeadActions({ lead, rights }: { lead: LeadDetail; rights: ActionRights }) {
  const { message, modal } = AntApp.useApp();
  const confirmDanger = useConfirmDanger();
  const mutation = useLeadAction(lead.id);
  const [dialog, setDialog] = useState<Dialog | null>(null);
  const s = leadActionStates(lead, rights);

  const run = async (action: LeadAction): Promise<boolean> => {
    try {
      await mutation.mutateAsync(action);
      void message.success(t.actions.done);
      setDialog(null);
      return true;
    } catch (error) {
      void message.error(errorText((error as ApiError).code, (error as Error).message));
      return false;
    }
  };
  const take = () => {
    const name = lead.assigned_user_name ?? ownerModeLabel("human");
    if (!isTakeover(lead, rights)) return void run({ kind: "take" });
    confirmDanger({
      title: t.confirm.takeOver.replace("{name}", name),
      content: t.confirm.takeOverHint.replace(/\{name\}/g, name),
      okText: t.actions.take,
      onOk: () => run({ kind: "take" }),
    });
  };
  const newDeal = () => {
    void modal.confirm({
      title: t.actions.newDeal,
      content: t.actions.newDealConfirm,
      okText: t.actions.newDeal,
      cancelText: t.actions.cancel,
      onOk: () => run({ kind: "newDeal" }),
    });
  };
  const open = (d: Dialog) => () => {
    setDialog(d);
  };

  return (
    <>
      <Space wrap>
        <ActionButton state={s.take} primary loading={mutation.isPending} onClick={take}>
          {t.actions.take}
        </ActionButton>
        <ActionButton state={s.returnToBot} onClick={open("return")}>
          {t.actions.returnToBot}
        </ActionButton>
        <ActionButton state={s.snooze} onClick={open("snooze")}>
          {t.actions.snooze}
        </ActionButton>
        <ActionButton state={s.close} onClick={open("won")}>
          {t.actions.won}
        </ActionButton>
        <ActionButton state={s.close} danger onClick={open("lost")}>
          {t.actions.lost}
        </ActionButton>
        {s.makeCustomer.visible ? <MakeCustomer leadId={lead.id} /> : null}
        <ActionButton state={s.newDeal} onClick={newDeal}>
          {t.actions.newDeal}
        </ActionButton>
        {s.assign.visible && !s.assign.reason ? (
          <AssignLead
            lead={lead}
            run={async (a) => {
              await run(a);
            }}
            busy={mutation.isPending}
          />
        ) : null}
        <ActionButton state={s.note} onClick={open("note")}>
          {t.actions.note}
        </ActionButton>
      </Space>
      <LeadActionDialog
        dialog={dialog}
        busy={mutation.isPending}
        onRun={run}
        onClose={() => {
          setDialog(null);
        }}
      />
    </>
  );
}
