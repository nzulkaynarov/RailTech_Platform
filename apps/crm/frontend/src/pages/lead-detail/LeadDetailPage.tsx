import { Alert, Card, Grid, Space, Tabs } from "antd";
import type { ReactNode } from "react";
import { Link, useParams } from "react-router";

import type { LeadDetail } from "../../api/generated/model";
import {
  useDecisions,
  useLead,
  useLeadAction,
  useMe,
  useMessages,
  usePermissionsQuery,
  useTeam,
} from "../../api/queries";
import { allowed } from "../../app/providers/access";
import { ChatThread } from "../../components/ChatThread";
import { DecisionsPanel } from "../../components/DecisionsPanel";
import { LeadActions, OwnerBanner } from "../../components/LeadActions";
import { type ActionRights, leadActionPlan, replyState } from "../../components/leadActionRules";
import { Owner } from "../../components/Owner";
import { PageBody } from "../../components/PageBody";
import { PageHeader } from "../../components/PageHeader";
import { PageState } from "../../components/PageState";
import { QueueNav } from "../../components/QueueNav";
import { StageBadge } from "../../components/StageBadge";
import { leadLinkText } from "../../domain/entities";
import { useApiErrorToast } from "../../hooks/useApiErrorToast";
import { t } from "../../i18n/ru";
import "../../styles/workspace.css";
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
  const messages = useMessages(lead.id);
  const team = useTeam();
  const action = useLeadAction(lead.id);
  const onError = useApiErrorToast();
  const reply = replyState(lead, rights);
  const authorName = (userId: number) => team.data?.find((m) => m.id === userId)?.full_name;
  const send = async (text: string) => {
    try {
      await action.mutateAsync({ kind: "reply", text });
    } catch (error) {
      onError(error);
      throw error;
    }
  };
  return (
    <PageState query={messages} variant="section">
      <ChatThread
        messages={messages.data ?? []}
        canReply={reply.can}
        hint={reply.hint}
        sending={action.isPending}
        language={lead.language}
        authorName={authorName}
        onSend={send}
      />
    </PageState>
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

/** Шапка: имя, стадия и ответственный (видны и на телефоне), действия и баннер «Лида ведёт …». */
function LeadHeader({ lead, rights }: { lead: LeadDetail; rights: ActionRights }) {
  const plan = leadActionPlan(lead, rights);
  return (
    <PageHeader
      back="/leads"
      nav={rights.take ? <QueueNav leadId={lead.id} /> : null}
      title={leadLinkText(lead.id, lead.display_name)}
      extra={<LeadActions lead={lead} rights={rights} />}
    >
      <div className="lead-meta">
        <StageBadge stage={lead.stage} />
        <span>
          {t.leads.owner}: <Owner lead={lead} />
        </span>
      </div>
      {plan.ownerBanner ? (
        <div className="lead-banner">
          <OwnerBanner banner={plan.ownerBanner} />
        </div>
      ) : null}
      {lead.open_service_request_id && lead.client_id ? (
        <div className="lead-banner">
          <Alert
            type="info"
            showIcon
            message={t.lead.openRequest}
            description={t.lead.openRequestHint}
            action={<Link to={`/clients/${String(lead.client_id)}`}>{t.inbox.openClient}</Link>}
          />
        </div>
      ) : null}
    </PageHeader>
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
        <PageBody>
          <LeadHeader lead={lead.data} rights={rights} />
          <Layout
            chat={<Chat lead={lead.data} rights={rights} />}
            details={
              <Space direction="vertical" size={16} style={{ width: "100%" }}>
                <LeadSummary lead={lead.data} />
                <LeadNotes leadId={id} />
              </Space>
            }
            why={<DecisionsPanel query={decisions} />}
          />
        </PageBody>
      ) : null}
    </PageState>
  );
}
