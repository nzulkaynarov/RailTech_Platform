import { Button, Card, Grid, List, Tag, Tooltip, Typography } from "antd";

import type { EscalationOut, LeadOut } from "../../api/generated/model";
import { useInbox, useMe, usePermissionsQuery } from "../../api/queries";
import { allowed } from "../../app/providers/access";
import { EmptyState, type EmptyStateProps } from "../../components/EmptyState";
import { LeadLink } from "../../components/EntityLink";
import { PageBody } from "../../components/PageBody";
import { PageHeader } from "../../components/PageHeader";
import { PageState } from "../../components/PageState";
import { PriorityTag, StageBadge } from "../../components/StageBadge";
import { reasonLabel, slaColor, unreadLabel } from "../../domain/labels";
import { formatWait, isWaiting, slaState, sortHandoffs } from "../../domain/sla";
import { useNow } from "../../hooks/useNow";
import { useTakeAndOpen } from "../../hooks/useLeadActionRunner";
import { t } from "../../i18n/ru";
import { formatDateTime, formatWhen, fromNow } from "../../lib/time";
import "../../styles/workspace.css";
import { ServiceRequestsColumn } from "./ServiceRequestsColumn";
import "../pages.css";

/** «Забрать» прямо из очереди и сразу в карточку лида (как Intercom «Assign to me»). */
function QuickTake({ lead }: { lead: LeadOut }) {
  const { takeAndOpen, busy } = useTakeAndOpen(lead.id);
  const phone = Grid.useBreakpoint().sm === false;
  return (
    <Button
      size={phone ? "large" : "small"}
      block={phone}
      type="primary"
      className="touch-target"
      loading={busy}
      onClick={() => void takeAndOpen()}
    >
      {t.actions.take}
    </Button>
  );
}

/** Сколько ждёт передача; цвет — по сроку реакции из настроек (через `sla_due_at`). */
function SlaTimer({ escalation, now }: { escalation: EscalationOut; now: Date }) {
  const sla = slaState(escalation, now);
  const wait = formatWait(sla.waitingMs);
  const text =
    sla.level === "snoozed" && sla.snoozedUntil
      ? t.inbox.snoozedUntil.replace("{time}", formatWhen(sla.snoozedUntil, now))
      : (sla.level === "overdue" ? t.inbox.overdue : t.inbox.waiting).replace("{time}", wait);
  const title = t.inbox.slaTooltip
    .replace("{from}", formatDateTime(sla.since))
    .replace("{due}", formatDateTime(sla.dueAt));
  return (
    <Tag color={slaColor(sla.level)}>
      <time dateTime={sla.since.toISOString()} title={title}>
        {text}
      </time>
    </Tag>
  );
}

function LastMessage({ at }: { at: string | null }) {
  if (!at) return null;
  return (
    <Tooltip title={formatDateTime(at)}>
      <Typography.Text type="secondary">
        <time dateTime={at}>{fromNow(at)}</time>
      </Typography.Text>
    </Tooltip>
  );
}

type ItemProps = { lead: LeadOut; canTake: boolean; now: Date };

function LeadItem({ lead, canTake, now }: ItemProps) {
  const free = lead.owner_mode !== "human";
  const e = lead.escalation;
  const unread = unreadLabel();
  return (
    <List.Item
      className={e?.priority === "hot" ? "inbox-hot" : ""}
      actions={canTake && free ? [<QuickTake key="take" lead={lead} />] : []}
    >
      <List.Item.Meta
        title={
          <span className="inbox-item-title">
            <LeadLink id={lead.id} name={lead.display_name} />
            {e ? <PriorityTag priority={e.priority} /> : null}
            {lead.unread ? <Tag color={unread.color}>{unread.label}</Tag> : null}
          </span>
        }
        description={
          <span className="lead-card-row">
            {e && isWaiting(e) ? (
              <SlaTimer escalation={e} now={now} />
            ) : (
              <LastMessage at={lead.last_lead_msg_at} />
            )}
            <StageBadge stage={lead.stage} />
            {e ? (
              <Typography.Text>{e.reason_codes.map(reasonLabel).join(", ")}</Typography.Text>
            ) : null}
            {lead.need_summary ? (
              <Typography.Text type="secondary">{lead.need_summary}</Typography.Text>
            ) : null}
          </span>
        }
      />
    </List.Item>
  );
}

type ColumnProps = Omit<ItemProps, "lead"> & {
  title: string;
  empty: EmptyStateProps;
  leads: LeadOut[];
};

function Column({ title, empty, leads, canTake, now }: ColumnProps) {
  return (
    <Card title={`${title} · ${String(leads.length)}`} size="small">
      {leads.length ? (
        <List
          dataSource={leads}
          renderItem={(lead) => <LeadItem lead={lead} canTake={canTake} now={now} />}
        />
      ) : (
        <EmptyState {...empty} />
      )}
    </Card>
  );
}

/** Входящие (SPEC §10.1): открытые передачи (горячие и дольше ждущие первыми), мои лиды, без ответственного. */
export function InboxPage() {
  const query = useInbox();
  const me = useMe();
  const perms = usePermissionsQuery();
  const now = useNow();
  const canTake = allowed(perms.data, "leads", "take") && Boolean(me.data);
  const canSeeClients = allowed(perms.data, "clients", "read");
  const data = query.data;
  return (
    <PageBody>
      <PageHeader title={t.page.inbox} />
      <PageState query={query} ready={Boolean(data)}>
        {data ? (
          <div className="inbox-grid">
            <Column
              title={t.inbox.escalations}
              empty={{ title: t.inbox.emptyEscalations }}
              leads={sortHandoffs(data.escalations)}
              canTake={canTake}
              now={now}
            />
            <Column
              title={t.inbox.mine}
              empty={{ title: t.inbox.emptyMine, hint: t.inbox.emptyMineHint }}
              leads={data.mine}
              canTake={false}
              now={now}
            />
            <Column
              title={t.inbox.unassigned}
              empty={{ title: t.inbox.emptyUnassigned }}
              leads={data.unassigned}
              canTake={canTake}
              now={now}
            />
            {canSeeClients ? <ServiceRequestsColumn now={now} /> : null}
          </div>
        ) : null}
      </PageState>
    </PageBody>
  );
}
