import { App as AntApp, Card, Grid, Space, Tabs } from "antd";
import type { ReactNode } from "react";
import { useParams } from "react-router";

import type { LeadDetail } from "../../api/generated/model";
import type { ApiError } from "../../api/http";
import {
  useDecisions,
  useLead,
  useLeadAction,
  useMe,
  useMessages,
  usePermissionsQuery,
} from "../../api/queries";
import { allowed } from "../../app/providers/access";
import { ChatThread } from "../../components/ChatThread";
import { DecisionsPanel } from "../../components/DecisionsPanel";
import { LeadActions } from "../../components/LeadActions";
import { type ActionRights, replyState } from "../../components/leadActionRules";
import { PageHeader } from "../../components/PageHeader";
import { PageState } from "../../components/PageState";
import { errorText, t } from "../../i18n/ru";
import { LeadNotes, LeadSummary } from "./LeadSummary";
import "../pages.css";

function useRights(): ActionRights | null {
  const me = useMe();
  const perms = usePermissionsQuery();
  if (!me.data) return null;
  return {
    take: allowed(perms.data, "leads", "take"),
    work: allowed(perms.data, "leads", "work"),
    note: allowed(perms.data, "leads", "note"),
    reply: allowed(perms.data, "leads", "reply"),
    clients: allowed(perms.data, "clients", "write"),
    userId: me.data.id,
    isAdmin: me.data.roles.includes("admin"),
  };
}

function Chat({ lead, rights }: { lead: LeadDetail; rights: ActionRights }) {
  const { message } = AntApp.useApp();
  const messages = useMessages(lead.id);
  const action = useLeadAction(lead.id);
  const reply = replyState(lead, rights);
  const send = async (text: string) => {
    try {
      await action.mutateAsync({ kind: "reply", text });
    } catch (error) {
      void message.error(errorText((error as ApiError).code));
      throw error;
    }
  };
  return (
    <ChatThread
      messages={messages.data ?? []}
      canReply={reply.can}
      hint={reply.hint}
      sending={action.isPending}
      onSend={send}
    />
  );
}

/** Три колонки на десктопе; на телефоне — вкладки, переписка первой (U-12). */
function Layout({ chat, details, why }: { chat: ReactNode; details: ReactNode; why: ReactNode }) {
  const screens = Grid.useBreakpoint();
  if (screens.md === false) {
    return (
      <Tabs
        items={[
          { key: "chat", label: t.lead.tabs.chat, children: chat },
          { key: "details", label: t.lead.tabs.details, children: details },
          { key: "why", label: t.lead.tabs.why, children: why },
        ]}
      />
    );
  }
  return (
    <div className="lead-grid">
      {details}
      <Card size="small" title={t.lead.chat}>
        {chat}
      </Card>
      <Card size="small" title={t.lead.why}>
        {why}
      </Card>
    </div>
  );
}

/** Карточка лида (SPEC §10.1): резюме · переписка · «Почему система так решила». */
export function LeadDetailPage() {
  const id = Number(useParams()["id"]);
  const lead = useLead(id);
  const decisions = useDecisions(id);
  const rights = useRights();
  return (
    <PageState query={lead} ready={Boolean(lead.data && rights)}>
      {lead.data && rights ? (
        <Space direction="vertical" size={16} style={{ width: "100%" }}>
          <PageHeader
            back="/leads"
            title={`#${String(lead.data.id)} · ${lead.data.display_name || t.common.none}`}
            extra={<LeadActions lead={lead.data} rights={rights} />}
          />
          <Layout
            chat={<Chat lead={lead.data} rights={rights} />}
            details={
              <Space direction="vertical" size={16} style={{ width: "100%" }}>
                <LeadSummary lead={lead.data} />
                <LeadNotes leadId={id} />
              </Space>
            }
            why={<DecisionsPanel decisions={decisions.data} />}
          />
        </Space>
      ) : null}
    </PageState>
  );
}
