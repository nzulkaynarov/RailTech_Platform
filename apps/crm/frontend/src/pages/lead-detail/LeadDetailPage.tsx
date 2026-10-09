import { App as AntApp, Card, Descriptions, List, Space, Tag, Typography } from "antd";
import dayjs from "dayjs";
import { useParams } from "react-router";

import type { LeadDetail } from "../../api/generated/model";
import type { ApiError } from "../../api/http";
import {
  useDecisions,
  useLead,
  useLeadAction,
  useMe,
  useMessages,
  useNotes,
  usePermissionsQuery,
} from "../../api/queries";
import { allowed } from "../../app/providers/access";
import { ChatThread } from "../../components/ChatThread";
import { DecisionsPanel } from "../../components/DecisionsPanel";
import { EscalationReason } from "../../components/EscalationReason";
import { LeadActions } from "../../components/LeadActions";
import type { ActionRights } from "../../components/leadActionRules";
import { StageBadge } from "../../components/StageBadge";
import { errorText, t } from "../../i18n/ru";
import "../pages.css";

function Summary({ lead }: { lead: LeadDetail }) {
  const q = lead.qualification as Record<string, unknown>;
  const fields = ["company", "company_size", "region", "timeline", "decision_role", "budget_hint"];
  return (
    <Card size="small" title={t.lead.summary}>
      <Descriptions column={1} size="small">
        <Descriptions.Item label={t.leads.stage}>
          <StageBadge stage={lead.stage} />
        </Descriptions.Item>
        <Descriptions.Item label={t.leads.score}>{lead.score}</Descriptions.Item>
        <Descriptions.Item label={t.leads.owner}>
          {t.owner[lead.owner_mode] ?? lead.owner_mode}
        </Descriptions.Item>
        <Descriptions.Item label={t.leads.language}>
          {lead.language.toUpperCase()}
        </Descriptions.Item>
        <Descriptions.Item label={t.lead.consent}>
          {lead.consent_given_at
            ? dayjs(lead.consent_given_at).format("DD.MM.YYYY")
            : t.lead.consentNo}
        </Descriptions.Item>
        <Descriptions.Item label={t.leads.need}>
          {lead.need_summary ?? t.common.none}
        </Descriptions.Item>
        <Descriptions.Item label="Telegram">
          {lead.tg_username ? `@${lead.tg_username}` : t.common.none}
        </Descriptions.Item>
      </Descriptions>
      <Typography.Text strong>{t.lead.qualification}</Typography.Text>
      <div>
        {fields
          .filter((f) => q[f])
          .map((f) => (
            <Tag key={f}>{`${f}: ${String(q[f])}`}</Tag>
          ))}
        {lead.product_interest.map((p) => (
          <Tag color="blue" key={p}>
            {p}
          </Tag>
        ))}
      </div>
      {lead.escalation ? (
        <>
          <Typography.Text strong>{t.lead.escalation}</Typography.Text>
          <div>
            <EscalationReason escalation={lead.escalation} />
          </div>
        </>
      ) : null}
    </Card>
  );
}

function Notes({ leadId }: { leadId: number }) {
  const { data } = useNotes(leadId);
  if (!data?.length) return null;
  return (
    <Card size="small" title={t.lead.notes}>
      <List
        size="small"
        dataSource={data}
        renderItem={(n) => (
          <List.Item>
            <Space direction="vertical" size={0}>
              <Typography.Text>{n.text}</Typography.Text>
              <Typography.Text type="secondary">
                {dayjs(n.created_at).format("DD.MM HH:mm")}{" "}
                {n.visible_to_bot ? `· ${t.actions.noteForBot}` : ""}
              </Typography.Text>
            </Space>
          </List.Item>
        )}
      />
    </Card>
  );
}

/** Карточка лида (SPEC §10.1): резюме · переписка · «Почему система так решила». */
export function LeadDetailPage() {
  const id = Number(useParams()["id"]);
  const { message } = AntApp.useApp();
  const lead = useLead(id);
  const messages = useMessages(id);
  const decisions = useDecisions(id);
  const me = useMe();
  const perms = usePermissionsQuery();
  const action = useLeadAction(id);
  if (!lead.data || !me.data) return <Card loading />;

  const rights: ActionRights = {
    take: allowed(perms.data, "leads", "take"),
    work: allowed(perms.data, "leads", "work"),
    note: allowed(perms.data, "leads", "note"),
    clients: allowed(perms.data, "clients", "write"),
    userId: me.data.id,
    isAdmin: me.data.roles.includes("admin"),
  };
  const canReply =
    allowed(perms.data, "leads", "reply") &&
    lead.data.owner_mode === "human" &&
    (lead.data.assigned_user_id === me.data.id || rights.isAdmin);

  const send = async (text: string) => {
    try {
      await action.mutateAsync({ kind: "reply", text });
    } catch (error) {
      void message.error(errorText((error as ApiError).code));
      throw error;
    }
  };

  return (
    <Space direction="vertical" size={16} style={{ width: "100%" }}>
      <Space wrap>
        <Typography.Title level={4} style={{ margin: 0 }}>
          #{lead.data.id} · {lead.data.display_name || t.common.none}
        </Typography.Title>
        <LeadActions lead={lead.data} rights={rights} />
      </Space>
      <div className="lead-grid">
        <Space direction="vertical" size={16}>
          <Summary lead={lead.data} />
          <Notes leadId={id} />
        </Space>
        <Card size="small" title={t.lead.chat}>
          <ChatThread
            messages={messages.data ?? []}
            canReply={canReply}
            sending={action.isPending}
            onSend={send}
          />
        </Card>
        <Card size="small" title={t.lead.why}>
          <DecisionsPanel decisions={decisions.data} />
        </Card>
      </div>
    </Space>
  );
}
