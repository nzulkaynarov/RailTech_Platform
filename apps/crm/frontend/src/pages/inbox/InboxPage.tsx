import { Badge, Card, Empty, List, Space, Typography } from "antd";
import dayjs from "dayjs";
import { Link } from "react-router";

import type { LeadOut } from "../../api/generated/model";
import { useInbox } from "../../api/queries";
import { PriorityTag } from "../../components/EscalationReason";
import { StageBadge } from "../../components/StageBadge";
import { t } from "../../i18n/ru";
import "../pages.css";
import { reasonLabel } from "../../domain/labels";

function LeadItem({ lead }: { lead: LeadOut }) {
  return (
    <List.Item>
      <List.Item.Meta
        title={
          <Space wrap>
            <Link to={`/leads/${String(lead.id)}`}>
              #{lead.id} · {lead.display_name || t.common.none}
            </Link>
            {lead.escalation ? <PriorityTag priority={lead.escalation.priority} /> : null}
            <StageBadge stage={lead.stage} />
          </Space>
        }
        description={
          <Space direction="vertical" size={0}>
            {lead.need_summary ? <Typography.Text>{lead.need_summary}</Typography.Text> : null}
            {lead.escalation ? (
              <Typography.Text type="secondary">
                {lead.escalation.reason_codes.map(reasonLabel).join(", ")}
              </Typography.Text>
            ) : null}
            {lead.last_lead_msg_at ? (
              <Typography.Text type="secondary">
                {dayjs(lead.last_lead_msg_at).format("DD.MM HH:mm")}
              </Typography.Text>
            ) : null}
          </Space>
        }
      />
    </List.Item>
  );
}

function Column({ title, leads }: { title: string; leads: LeadOut[] }) {
  return (
    <Card
      title={
        <Badge count={leads.length} offset={[12, 0]}>
          {title}
        </Badge>
      }
      size="small"
    >
      {leads.length ? (
        <List dataSource={leads} renderItem={(lead) => <LeadItem lead={lead} />} />
      ) : (
        <Empty description={t.inbox.empty} />
      )}
    </Card>
  );
}

/** Входящие (SPEC §10.1): открытые эскалации (hot первыми), мои лиды, без владельца. */
export function InboxPage() {
  const { data, isLoading } = useInbox();
  if (isLoading || !data) return <Card loading />;
  return (
    <div className="inbox-grid">
      <Column title={t.inbox.escalations} leads={data.escalations} />
      <Column title={t.inbox.mine} leads={data.mine} />
      <Column title={t.inbox.unassigned} leads={data.unassigned} />
    </div>
  );
}
