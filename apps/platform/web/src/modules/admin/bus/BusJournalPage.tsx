import { Button, Card, Skeleton } from "antd";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useSearchParams } from "react-router";

import { PanelPortal } from "../../../app/shell/PanelSlot";
import type {
  BusDelivery,
  BusDomain,
  BusInboxEntry,
  BusJournal,
  BusSubscriber,
} from "../../../shared/api/generated/model";
import { useGetBusJournal } from "../../../shared/api/generated/platform-bff";
import { useDocumentTitle } from "../../../shared/lib/useDocumentTitle";
import { CounterCard, CounterGrid } from "../../../shared/ui/CounterCard";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { PageHeader } from "../../../shared/ui/PageHeader";
import { JournalFilter } from "../journal/JournalFilter";
import { DeliveryPanel, InboxPanel, RetryDeadPanel } from "./BusPanels";
import { DeliveriesView } from "./DeliveriesView";
import { deliveryKey, inboxKey } from "./format";
import { InboxView } from "./InboxView";
import { BusSourcesNote } from "./parts";
import { SubscribersView } from "./SubscribersView";

import "./bus.css";

const PATH = "/admin/bus";
const VIEWS = ["subscribers", "deliveries", "dlq", "inbox"] as const;
type View = (typeof VIEWS)[number];

type Selection =
  | { kind: "delivery"; item: BusDelivery }
  | { kind: "inbox"; item: BusInboxEntry }
  | { kind: "dead"; domain: BusDomain; subscriber: BusSubscriber };

function isView(value: string | null): value is View {
  return value !== null && (VIEWS as readonly string[]).includes(value);
}

function totals(journal: BusJournal | undefined) {
  const domains = journal?.domains ?? [];
  const subscribers = domains.flatMap((d) => d.subscribers);
  return {
    dlq: domains.reduce((sum, d) => sum + d.dlq_size, 0),
    pending: subscribers.reduce((sum, s) => sum + s.pending, 0),
    paused: subscribers.filter((s) => s.state === "paused").length,
    inboxFailed: domains.reduce((sum, d) => sum + d.inbox_failed + d.inbox_retrying, 0),
    names: [...new Set(subscribers.map((s) => s.name))].sort(),
  };
}

/**
 * Admin · Журнал интеграций (W13-A2): шина событий CRM, ERP и EDS в одном журнале вместо CLI `bus status|retry` и Django
 * admin ERP. Вверху — счётчики, ниже разделы: подписчики по доменам (состояние, предохранитель, «Повторить все dead»),
 * доставки с фильтрами, недоставленные (DLQ), входящие с ошибками. Подробности и повтор — в боковом окне с «Что
 * произойдёт». Только администратор (`admin` — полный); тел событий нет, только метаданные доставки.
 */
export function BusJournalPage() {
  const { t } = useTranslation(["bus", "modules"]);
  // Один «Журнал» (W15-H4): это его фильтр «Обмен между системами».
  const title = t("modules:admin.sections.audit");
  useDocumentTitle(title);
  const [params, setParams] = useSearchParams();
  const view: View = isView(params.get("view")) ? (params.get("view") as View) : "subscribers";
  const journal = useGetBusJournal();
  const [selection, setSelection] = useState<Selection | null>(null);
  const sums = useMemo(() => totals(journal.data), [journal.data]);

  const select = (next: Selection) => {
    setSelection(next);
    setParams(
      (prev) => {
        const out = new URLSearchParams(prev);
        out.set("panel", "open");
        return out;
      },
      { replace: true },
    );
  };
  const selectedDelivery = selection?.kind === "delivery" ? deliveryKey(selection.item) : null;
  const selectedInbox = selection?.kind === "inbox" ? inboxKey(selection.item) : null;
  const selectedDead =
    selection?.kind === "dead"
      ? { domain: selection.domain, name: selection.subscriber.name }
      : null;

  let subscribersBody;
  if (journal.isPending) {
    subscribersBody = <Skeleton active paragraph={{ rows: 8 }} title={false} />;
  } else if (journal.isError) {
    subscribersBody = (
      <Card>
        <EmptyState
          title={t("bus:loadError.title")}
          text={t("bus:loadError.text")}
          action={
            <Button
              onClick={() => {
                void journal.refetch();
              }}
            >
              {t("bus:loadError.retry")}
            </Button>
          }
        />
      </Card>
    );
  } else {
    subscribersBody = (
      <SubscribersView
        domains={journal.data.domains}
        selected={selectedDead}
        onRetryDead={(domain, subscriber) => {
          select({ kind: "dead", domain, subscriber });
        }}
      />
    );
  }

  const counter = (key: "dlq" | "pending" | "paused" | "inboxFailed", target: View) => (
    <CounterCard
      label={t(`bus:counters.${key}`)}
      value={journal.data ? sums[key] : "—"}
      source={t("bus:counters.source")}
      to={`${PATH}?view=${target}`}
    />
  );

  return (
    <div className="pf-bus">
      <PageHeader title={title} subtitle={t("bus:subtitle")} />
      <JournalFilter current="systems" />
      <BusSourcesNote
        sources={journal.data?.sources}
        onRetry={() => {
          void journal.refetch();
        }}
      />
      <CounterGrid>
        {counter("dlq", "dlq")}
        {counter("pending", "deliveries")}
        {counter("paused", "subscribers")}
        {counter("inboxFailed", "inbox")}
      </CounterGrid>
      <nav className="pf-bus-views" aria-label={t("bus:views.label")}>
        <ul>
          {VIEWS.map((key) => (
            <li key={key}>
              <Link
                to={`${PATH}?view=${key}`}
                className="pf-bus-view pf-focusable"
                aria-current={key === view ? "page" : undefined}
              >
                {t(`bus:views.${key}`)}
              </Link>
            </li>
          ))}
        </ul>
      </nav>
      {view === "subscribers" ? subscribersBody : null}
      {view === "deliveries" || view === "dlq" ? (
        <DeliveriesView
          key={view}
          mode={view === "dlq" ? "dlq" : "all"}
          subscribers={sums.names}
          selectedKey={selectedDelivery}
          onOpen={(item) => {
            select({ kind: "delivery", item });
          }}
        />
      ) : null}
      {view === "inbox" ? (
        <InboxView
          selectedKey={selectedInbox}
          onOpen={(item) => {
            select({ kind: "inbox", item });
          }}
        />
      ) : null}
      {selection ? (
        <PanelPortal tab="card">
          {selection.kind === "delivery" ? (
            <DeliveryPanel key={selectedDelivery} delivery={selection.item} />
          ) : selection.kind === "inbox" ? (
            <InboxPanel key={selectedInbox} entry={selection.item} />
          ) : (
            <RetryDeadPanel
              key={`${selection.domain}:${selection.subscriber.name}`}
              domain={selection.domain}
              subscriber={selection.subscriber}
            />
          )}
        </PanelPortal>
      ) : null}
    </div>
  );
}
