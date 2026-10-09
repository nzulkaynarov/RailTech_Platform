import { App as AntApp, Badge, Button, Card, Empty, List, Space, Tooltip, Typography } from "antd";
import { Link } from "react-router";

import type { LeadOut } from "../../api/generated/model";
import type { ApiError } from "../../api/http";
import { useInbox, useLeadAction, useMe, usePermissionsQuery } from "../../api/queries";
import { allowed } from "../../app/providers/access";
import { PageHeader } from "../../components/PageHeader";
import { PageState } from "../../components/PageState";
import { PriorityTag, StageBadge } from "../../components/StageBadge";
import { reasonLabel } from "../../domain/labels";
import { errorText, t } from "../../i18n/ru";
import { formatDateTime, fromNow } from "../../lib/time";
import "../pages.css";

/** «Забрать» прямо из очереди — как в Intercom/HubSpot (аудит UI U-06). */
function QuickTake({ lead }: { lead: LeadOut }) {
  const { message } = AntApp.useApp();
  const take = useLeadAction(lead.id);
  return (
    <Button
      size="small"
      type="primary"
      loading={take.isPending}
      onClick={() => {
        take.mutateAsync({ kind: "take" }).then(
          () => void message.success(t.actions.done),
          (e: unknown) => void message.error(errorText((e as ApiError).code)),
        );
      }}
    >
      {t.actions.take}
    </Button>
  );
}

function LeadItem({ lead, canTake }: { lead: LeadOut; canTake: boolean }) {
  const free = lead.owner_mode !== "human";
  return (
    <List.Item actions={canTake && free ? [<QuickTake key="take" lead={lead} />] : []}>
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
              <Tooltip title={formatDateTime(lead.last_lead_msg_at)}>
                <Typography.Text type="secondary">{fromNow(lead.last_lead_msg_at)}</Typography.Text>
              </Tooltip>
            ) : null}
          </Space>
        }
      />
    </List.Item>
  );
}

type ColumnProps = { title: string; empty: string; leads: LeadOut[]; canTake: boolean };

function Column({ title, empty, leads, canTake }: ColumnProps) {
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
        <List
          dataSource={leads}
          renderItem={(lead) => <LeadItem lead={lead} canTake={canTake} />}
        />
      ) : (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={empty} />
      )}
    </Card>
  );
}

/** Входящие (SPEC §10.1): открытые эскалации (hot первыми), мои лиды, без владельца. */
export function InboxPage() {
  const query = useInbox();
  const me = useMe();
  const perms = usePermissionsQuery();
  const canTake = allowed(perms.data, "leads", "take") && Boolean(me.data);
  const data = query.data;
  return (
    <>
      <PageHeader title={t.page.inbox} />
      <PageState query={query} ready={Boolean(data)}>
        {data ? (
          <div className="inbox-grid">
            <Column
              title={t.inbox.escalations}
              empty={t.inbox.emptyEscalations}
              leads={data.escalations}
              canTake={canTake}
            />
            <Column
              title={t.inbox.mine}
              empty={t.inbox.emptyMine}
              leads={data.mine}
              canTake={false}
            />
            <Column
              title={t.inbox.unassigned}
              empty={t.inbox.emptyUnassigned}
              leads={data.unassigned}
              canTake={canTake}
            />
          </div>
        ) : null}
      </PageState>
    </>
  );
}
