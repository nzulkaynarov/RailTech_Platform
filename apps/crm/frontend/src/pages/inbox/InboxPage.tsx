import { Flex, Grid, List, Select, Tabs, Tag, Tooltip, Typography } from "antd";
import { type ReactNode, useState } from "react";
import { useSearchParams } from "react-router";

import type { EscalationOut, InboxResponse, LeadOut } from "../../api/generated/model";
import { useInbox, useMe, useOpenServiceRequests, usePermissionsQuery } from "../../api/queries";
import { allowed } from "../../app/providers/access";
import { EmptyState, type EmptyStateProps } from "../../components/EmptyState";
import { LeadLink } from "../../components/EntityLink";
import { LeadPreviewDrawer, TakeButton } from "../../components/LeadPreviewDrawer";
import { PageBody } from "../../components/PageBody";
import { PageHeader } from "../../components/PageHeader";
import { PageState } from "../../components/PageState";
import { PriorityTag, StageBadge } from "../../components/StageBadge";
import { INBOX_TABS, type InboxTab, pickInboxTab } from "../../domain/inboxTabs";
import { reasonLabel, slaColor, unreadLabel } from "../../domain/labels";
import { HOUR, formatWait, isWaiting, slaState, sortHandoffs } from "../../domain/sla";
import { useNow } from "../../hooks/useNow";
import { t } from "../../i18n/ru";
import { isRowClick } from "../../lib/rowClick";
import { formatDateTime, formatWhen, fromNow } from "../../lib/time";
import "../../styles/workspace.css";
import { ServiceRequestsList } from "./ServiceRequestsList";
import "../pages.css";

/** Сколько ждёт передача; цвет — по сроку реакции из настроек (через `sla_due_at`). */
function SlaTimer({ escalation, now }: { escalation: EscalationOut; now: Date }) {
  const sla = slaState(escalation, now);
  const wait = formatWait(sla.waitingMs);
  const text =
    sla.level === "snoozed" && sla.snoozedUntil
      ? t.inbox.snoozedUntil.replace("{time}", formatWhen(sla.snoozedUntil, now))
      : (sla.level === "overdue"
          ? t.inbox.overdue
          : sla.dueAt.getTime() - now.getTime() > HOUR
            ? t.inbox.waitingDue.replace("{due}", formatWhen(sla.dueAt, now))
            : t.inbox.waiting
        ).replace("{time}", wait);
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

type ItemProps = { lead: LeadOut; canTake: boolean; now: Date; onOpen: (id: number) => void };

/** Строка: имя · приоритет · ждёт N мин; ниже стадия, причины и потребность; справа «Забрать». */
function LeadItem({ lead, canTake, now, onOpen }: ItemProps) {
  const e = lead.escalation;
  const unread = unreadLabel();
  return (
    <List.Item
      className={e?.priority === "hot" ? "inbox-row inbox-hot" : "inbox-row"}
      onClick={(event) => {
        if (isRowClick(event.target)) onOpen(lead.id);
      }}
      actions={
        canTake && lead.owner_mode !== "human" ? [<TakeButton key="take" leadId={lead.id} />] : []
      }
    >
      <List.Item.Meta
        title={
          <span className="inbox-item-title">
            <LeadLink id={lead.id} name={lead.display_name} />
            {e ? <PriorityTag priority={e.priority} /> : null}
            {lead.unread ? <Tag color={unread.color}>{unread.label}</Tag> : null}
            {e && isWaiting(e) ? (
              <SlaTimer escalation={e} now={now} />
            ) : (
              <LastMessage at={lead.last_lead_msg_at} />
            )}
          </span>
        }
        description={
          <>
            <span className="lead-card-row">
              <StageBadge stage={lead.stage} />
              {e ? (
                <Typography.Text>{e.reason_codes.map(reasonLabel).join(", ")}</Typography.Text>
              ) : null}
            </span>
            {lead.need_summary ? (
              <Typography.Paragraph type="secondary" ellipsis className="inbox-need">
                {lead.need_summary}
              </Typography.Paragraph>
            ) : null}
          </>
        }
      />
    </List.Item>
  );
}

type LeadListProps = Omit<ItemProps, "lead"> & { leads: LeadOut[]; empty: EmptyStateProps };

function LeadList({ leads, empty, ...rest }: LeadListProps) {
  if (!leads.length) return <EmptyState compact {...empty} />;
  return (
    <List
      size="small"
      dataSource={leads}
      renderItem={(lead) => <LeadItem lead={lead} {...rest} />}
    />
  );
}

type TabSpec = { leads: LeadOut[]; empty: EmptyStateProps; take: boolean };

function leadTabs(data: InboxResponse): Record<Exclude<InboxTab, "requests">, TabSpec> {
  return {
    handoffs: {
      leads: sortHandoffs(data.escalations),
      empty: { title: t.inbox.emptyEscalations },
      take: true,
    },
    mine: {
      leads: data.mine,
      empty: { title: t.inbox.emptyMine, hint: t.inbox.emptyMineHint },
      take: false,
    },
    unassigned: { leads: data.unassigned, empty: { title: t.inbox.emptyUnassigned }, take: true },
  };
}

type Section = { key: InboxTab; label: string; children: ReactNode };
type SectionsProps = { active: InboxTab; items: Section[]; onChange: (tab: string) => void };

/**
 * Десктоп — вкладки; телефон — выпадающий список разделов (четыре вкладки со счётчиками
 * не помещаются в 390 px, а «…» antd внутри `tablist` нарушает axe aria-required-children).
 */
function Sections({ active, items, onChange }: SectionsProps) {
  const phone = Grid.useBreakpoint().sm === false;
  if (!phone) {
    return (
      <Tabs aria-label={t.inbox.tabsLabel} activeKey={active} items={items} onChange={onChange} />
    );
  }
  return (
    <Flex vertical gap="small">
      <Select
        aria-label={t.inbox.tabsLabel}
        value={active}
        options={items.map(({ key, label }) => ({ value: key, label }))}
        onChange={onChange}
        size="large"
      />
      {items.find((item) => item.key === active)?.children}
    </Flex>
  );
}

/**
 * Входящие (SPEC §10.1, UX волна 2): один список с вкладками «Передачи · Мои · Без ответственного ·
 * Запросы клиентов» и счётчиками; вкладка — в URL. Клик по строке — краткая сводка справа.
 */
export function InboxPage() {
  const query = useInbox();
  const me = useMe();
  const perms = usePermissionsQuery();
  const now = useNow();
  const [search, setSearch] = useSearchParams();
  const [preview, setPreview] = useState<number | null>(null);
  const canTake = allowed(perms.data, "leads", "take") && Boolean(me.data);
  const canSeeClients = allowed(perms.data, "clients", "read");
  const requests = useOpenServiceRequests(canSeeClients);
  const data = query.data;
  const specs = data ? leadTabs(data) : null;
  const available = canSeeClients ? INBOX_TABS : INBOX_TABS.filter((k) => k !== "requests");
  const counts = {
    handoffs: specs?.handoffs.leads.length,
    mine: specs?.mine.leads.length,
    unassigned: specs?.unassigned.leads.length,
    requests: requests.data?.length,
  };
  const active = pickInboxTab(search.get("tab"), counts, available);
  const items = available.map((key) => {
    const spec = key === "requests" ? null : specs?.[key];
    return {
      key,
      label: `${t.inbox.tabs[key] ?? key} · ${String(counts[key] ?? 0)}`,
      children: spec ? (
        <LeadList
          leads={spec.leads}
          empty={spec.empty}
          canTake={canTake && spec.take}
          now={now}
          onOpen={setPreview}
        />
      ) : key === "requests" ? (
        <ServiceRequestsList query={requests} now={now} />
      ) : null,
    };
  });
  return (
    <PageBody>
      <PageHeader title={t.page.inbox} />
      <PageState query={query} ready={Boolean(data)}>
        <Sections
          active={active}
          items={items}
          onChange={(tab) => {
            setSearch({ tab }, { replace: true });
          }}
        />
      </PageState>
      <LeadPreviewDrawer
        leadId={preview}
        canTake={canTake}
        onClose={() => {
          setPreview(null);
        }}
      />
    </PageBody>
  );
}
