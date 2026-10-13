import { Flex, Grid, List, Select, Splitter, Tabs, Tag, Tooltip, Typography } from "antd";
import type { ReactNode } from "react";
import { useSearchParams } from "react-router";

import type { EscalationOut, InboxResponse, LeadOut } from "../../api/generated/model";
import { useInbox, useMe, useOpenServiceRequests, usePermissionsQuery } from "../../api/queries";
import { allowed } from "../../app/providers/access";
import { EmptyState, type EmptyStateProps } from "../../components/EmptyState";
import { LeadLink } from "../../components/EntityLink";
import { LeadPreviewDrawer, LeadPreviewPane, TakeButton } from "../../components/LeadPreviewDrawer";
import { PageBody } from "../../components/PageBody";
import { PageHeader } from "../../components/PageHeader";
import { PageState } from "../../components/PageState";
import { PriorityTag, StageBadge } from "../../components/StageBadge";
import { INBOX_TABS, type InboxTab, pickInboxTab, pickPreviewLead } from "../../domain/inboxTabs";
import { reasonLabel, slaColor, unreadLabel } from "../../domain/labels";
import { HOUR, formatWait, isWaiting, slaState, sortHandoffs } from "../../domain/sla";
import { useNow } from "../../hooks/useNow";
import { t } from "../../i18n/ru";
import { isRowClick } from "../../lib/rowClick";
import { readSplit, saveSplit } from "../../lib/splitSize";
import { formatDateTime, formatWhen, fromNow } from "../../lib/time";
import "../../styles/workspace.css";
import { NewLeadButton } from "./NewLeadDialog";
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

type ItemProps = {
  lead: LeadOut;
  canTake: boolean;
  now: Date;
  selected: number | null;
  onOpen: (id: number) => void;
};

function rowClass(lead: LeadOut, selected: boolean): string {
  const hot = lead.escalation?.priority === "hot" ? " inbox-hot" : "";
  return `inbox-row${hot}${selected ? " inbox-row-selected" : ""}`;
}

/**
 * Строка: имя · приоритет · ждёт N мин; ниже стадия, причины и потребность; справа «Забрать».
 * Сводка открывается щелчком по строке или Enter на строке в фокусе (ссылка и кнопка — свои).
 */
function LeadItem({ lead, canTake, now, selected, onOpen }: ItemProps) {
  const e = lead.escalation;
  const unread = unreadLabel();
  const current = selected === lead.id;
  return (
    <List.Item
      className={rowClass(lead, current)}
      tabIndex={0}
      aria-current={current ? "true" : undefined}
      onClick={(event) => {
        if (isRowClick(event.target)) onOpen(lead.id);
      }}
      onKeyDown={(event) => {
        if (event.key === "Enter" && event.target === event.currentTarget) onOpen(lead.id);
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

/** Доля списка по умолчанию и пределы перетаскивания (сводка справа не уже ≈ 360 px). */
const LIST_SPLIT = { fallback: 60, min: 40, max: 70 };
const SPLIT_KEY = "inbox";

/** Широкий экран (≥ xl): список | сводка выбранного лида в antd `Splitter` (Refine/antd P2, п. 7). */
function ListWithPreview({ list, preview }: { list: ReactNode; preview: ReactNode }) {
  return (
    <Splitter
      className="inbox-split"
      onResizeEnd={(sizes) => {
        saveSplit(SPLIT_KEY, sizes);
      }}
    >
      <Splitter.Panel
        className="split-start"
        defaultSize={readSplit(SPLIT_KEY, LIST_SPLIT)}
        min={`${String(LIST_SPLIT.min)}%`}
        max={`${String(LIST_SPLIT.max)}%`}
      >
        {list}
      </Splitter.Panel>
      <Splitter.Panel className="split-end">{preview}</Splitter.Panel>
    </Splitter>
  );
}

/** Вкладка и выбранный лид — в адресе (`?tab=`, `?lead=`): перезагрузка сохраняет обе. */
function useInboxUrl() {
  const [search, setSearch] = useSearchParams();
  const update = (key: "tab" | "lead", value: string | null) => {
    setSearch(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (value === null) next.delete(key);
        else next.set(key, value);
        return next;
      },
      { replace: true },
    );
  };
  return {
    tabParam: search.get("tab"),
    selected: pickPreviewLead(search.get("lead")),
    setTab: (tab: string) => {
      update("tab", tab);
    },
    select: (id: number | null) => {
      update("lead", id === null ? null : String(id));
    },
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

/** Данные вкладок: списки, счётчики и права роли. */
function useInboxData() {
  const query = useInbox();
  const me = useMe();
  const perms = usePermissionsQuery();
  const canTake = allowed(perms.data, "leads", "take") && Boolean(me.data);
  const canCreate = allowed(perms.data, "leads", "create");
  const canSeeClients = allowed(perms.data, "clients", "read");
  const requests = useOpenServiceRequests(canSeeClients);
  const specs = query.data ? leadTabs(query.data) : null;
  const available = canSeeClients ? INBOX_TABS : INBOX_TABS.filter((k) => k !== "requests");
  const counts = {
    handoffs: specs?.handoffs.leads.length,
    mine: specs?.mine.leads.length,
    unassigned: specs?.unassigned.leads.length,
    requests: requests.data?.length,
  };
  return { query, requests, specs, available, counts, canTake, canCreate };
}

/**
 * Входящие (SPEC §10.1, UX волна 2): один список с вкладками «Передачи · Мои · Без ответственного ·
 * Запросы клиентов» и счётчиками; вкладка и выбранный лид — в URL. Щелчок по строке — сводка:
 * на широком экране в панели справа от списка, иначе в выезжающей панели.
 */
export function InboxPage() {
  const { query, requests, specs, available, counts, canTake, canCreate } = useInboxData();
  const now = useNow();
  const url = useInboxUrl();
  const wide = Grid.useBreakpoint().xl === true;
  const active = pickInboxTab(url.tabParam, counts, available);
  const leadList = (spec: TabSpec) => {
    const list = (
      <LeadList
        leads={spec.leads}
        empty={spec.empty}
        canTake={canTake && spec.take}
        now={now}
        selected={url.selected}
        onOpen={url.select}
      />
    );
    if (!wide) return list;
    const preview = <LeadPreviewPane leadId={url.selected} canTake={canTake} />;
    return <ListWithPreview list={list} preview={preview} />;
  };
  const items = available.map((key) => {
    const spec = key === "requests" ? null : specs?.[key];
    return {
      key,
      label: `${t.inbox.tabs[key] ?? key} · ${String(counts[key] ?? 0)}`,
      children: spec ? (
        leadList(spec)
      ) : key === "requests" ? (
        <ServiceRequestsList query={requests} now={now} />
      ) : null,
    };
  });
  return (
    <PageBody>
      <PageHeader title={t.page.inbox} extra={canCreate ? <NewLeadButton /> : null} />
      <PageState query={query} ready={Boolean(query.data)}>
        <Sections active={active} items={items} onChange={url.setTab} />
      </PageState>
      <LeadPreviewDrawer
        leadId={wide ? null : url.selected}
        canTake={canTake}
        onClose={() => {
          url.select(null);
        }}
      />
    </PageBody>
  );
}
