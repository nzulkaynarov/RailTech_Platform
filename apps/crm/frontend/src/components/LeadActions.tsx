import { DownOutlined } from "@ant-design/icons";
import { Alert, App as AntApp, Button, Dropdown, Grid, Space } from "antd";
import { useState } from "react";

import type { LeadDetail } from "../api/generated/model";
import { type LeadAction, useMessages } from "../api/queries";
import { useConfirmDanger } from "../hooks/useConfirmDanger";
import { useHandoffRetry } from "../hooks/useHandoffRetry";
import { useLeadActionRunner } from "../hooks/useLeadActionRunner";
import { t } from "../i18n/ru";
import "../styles/workspace.css";
import { AssignLead } from "./AssignLead";
import { lastUnanswered } from "../domain/unanswered";
import { type Dialog, LeadActionDialog } from "./LeadActionDialog";
import {
  type ActionKey,
  type ActionPlan,
  type ActionRights,
  DANGER_ACTIONS,
  leadActionPlan,
} from "./leadActionRules";
import { MakeCustomer } from "./MakeCustomer";

const LABEL: Record<ActionKey, string> = {
  acknowledge: t.actions.acknowledge,
  take: t.actions.take,
  takeOver: t.actions.takeOver,
  won: t.actions.won,
  lost: t.actions.lost,
  snooze: t.actions.snooze,
  unsnooze: t.actions.unsnooze,
  returnToBot: t.actions.returnToBot,
  assign: t.actions.assign,
  newDeal: t.actions.newDeal,
  makeCustomer: t.clients.makeCustomer,
  note: t.actions.note,
};

type Open = Dialog | "assign" | "makeCustomer";
const TEXT_DIALOGS: ReadonlySet<Open> = new Set(["return", "snooze", "lost", "won", "note"]);
const DIALOG_OF: Partial<Record<ActionKey, Open>> = {
  won: "won",
  lost: "lost",
  snooze: "snooze",
  returnToBot: "return",
  note: "note",
  assign: "assign",
  makeCustomer: "makeCustomer",
};

type Run = (action: LeadAction) => Promise<boolean>;

/** Что делает каждое действие: сразу, через подтверждение или через диалог. */
function useHandlers(lead: LeadDetail, run: Run, open: (d: Open) => void) {
  const { modal } = AntApp.useApp();
  const confirmDanger = useConfirmDanger();
  const handoff = useHandoffRetry(lead.client_id ?? null, lead.id);
  const name = lead.assigned_user_name ?? t.owner.human ?? "";
  const onAction = (key: ActionKey) => {
    if (key === "makeCustomer" && lead.stage === "customer") {
      // Клиент уже привязан к лиду, но не передан в ERP (FIX-34b): диалог выбора клиента не нужен.
      handoff.mutate();
      return;
    }
    const dialog = DIALOG_OF[key];
    if (dialog) {
      open(dialog);
      return;
    }
    if (key === "take" || key === "acknowledge" || key === "unsnooze") {
      void run({ kind: key });
      return;
    }
    if (key === "takeOver") {
      confirmDanger({
        title: t.confirm.takeOver.replace("{name}", name),
        content: t.confirm.takeOverHint.replace(/\{name\}/g, name),
        okText: t.actions.takeOver,
        onOk: () => run({ kind: "take" }),
      });
      return;
    }
    void modal.confirm({
      title: t.actions.newDeal,
      content: t.actions.newDealConfirm,
      okText: t.actions.newDeal,
      cancelText: t.actions.cancel,
      onOk: () => run({ kind: "newDeal" }),
    });
  };
  return { onAction, handoffBusy: handoff.isPending };
}

/** Чужой лид: одна строка «Лида ведёт {имя}» вместо ряда неактивных кнопок. */
export function OwnerBanner({ banner }: { banner: ActionPlan["ownerBanner"] }) {
  if (!banner) return null;
  return (
    <Alert
      type="info"
      showIcon
      message={t.lead.ownerBanner.replace("{name}", banner.name)}
      description={banner.hint ? t.lead.ownerBannerHint : undefined}
    />
  );
}

type ButtonsProps = {
  plan: ActionPlan;
  busy: boolean;
  onAction: (key: ActionKey) => void;
  backofficeMode?: string | undefined;
};

/** Одно главное действие и меню «Ещё» (одно оставшееся действие — обычной кнопкой). */
function ActionButtons({ plan, busy, onAction, backofficeMode }: ButtonsProps) {
  const screens = Grid.useBreakpoint();
  const size = screens.sm === false ? "large" : "middle";
  const { primary, more } = plan;
  const single = !primary && more.length === 1 ? more[0] : undefined;
  const labelFor = (key: ActionKey) =>
    key === "makeCustomer" && backofficeMode === "erp" ? t.clients.handoff : LABEL[key];

  return (
    <Space wrap className="lead-actions" role="group" aria-label={t.lead.actionsLabel}>
      {primary ? (
        <Button
          type="primary"
          size={size}
          loading={busy}
          onClick={() => {
            onAction(primary);
          }}
        >
          {labelFor(primary)}
        </Button>
      ) : null}
      {single ? (
        <Button
          size={size}
          danger={DANGER_ACTIONS.has(single)}
          onClick={() => {
            onAction(single);
          }}
        >
          {labelFor(single)}
        </Button>
      ) : null}
      {more.length && !single ? (
        <Dropdown
          trigger={["click"]}
          menu={{
            items: more.map((key) => ({
              key,
              label: labelFor(key),
              danger: DANGER_ACTIONS.has(key),
            })),
            onClick: ({ key }) => {
              onAction(key as ActionKey);
            },
          }}
        >
          <Button size={size}>
            <Space size={4}>
              {t.lead.more}
              <DownOutlined aria-hidden />
            </Space>
          </Button>
        </Dropdown>
      ) : null}
    </Space>
  );
}

/** Действия карточки лида: иерархия по состоянию (дизайн-аудит 2026-10-11, волна B). */
export function LeadActions({ lead, rights }: { lead: LeadDetail; rights: ActionRights }) {
  const plan = leadActionPlan(lead, rights);
  const { run, busy: running } = useLeadActionRunner(lead.id);
  const [dialog, setDialog] = useState<Open | null>(null);
  const close = () => {
    setDialog(null);
  };
  const runAndClose: Run = async (action) => {
    const ok = await run(action);
    if (ok) close();
    return ok;
  };
  const { onAction, handoffBusy } = useHandlers(lead, run, setDialog);
  const busy = running || handoffBusy;
  const available = new Set([plan.primary, ...plan.more]);
  const unanswered = lastUnanswered(useMessages(lead.id).data);
  return (
    <>
      <ActionButtons
        plan={plan}
        busy={busy}
        onAction={onAction}
        backofficeMode={lead.backoffice_mode}
      />
      <LeadActionDialog
        key={dialog ?? "closed"}
        dialog={dialog && TEXT_DIALOGS.has(dialog) ? (dialog as Dialog) : null}
        busy={busy}
        onRun={runAndClose}
        onClose={close}
        unanswered={unanswered}
      />
      {available.has("assign") ? (
        <AssignLead lead={lead} open={dialog === "assign"} busy={busy} onClose={close} run={run} />
      ) : null}
      {available.has("makeCustomer") ? (
        <MakeCustomer
          leadId={lead.id}
          open={dialog === "makeCustomer"}
          onClose={close}
          backofficeMode={lead.backoffice_mode}
        />
      ) : null}
    </>
  );
}
