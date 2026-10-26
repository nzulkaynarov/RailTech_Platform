import { useInfiniteQuery } from "@tanstack/react-query";
import { Button, Card, Input, Skeleton, Table } from "antd";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { useViewport } from "../../../app/shell/useViewport";
import type {
  BusDelivery,
  BusDeliveryStatus,
  BusDomain,
  ListBusDeliveriesParams,
} from "../../../shared/api/generated/model";
import {
  getListBusDeliveriesQueryKey,
  listBusDeliveries,
} from "../../../shared/api/generated/platform-bff";
import { useFormat } from "../../../shared/lib/useFormat";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { StatusTag } from "../../../shared/ui/StatusTag";
import {
  DELIVERY_TONE,
  DOMAINS,
  busErrorText,
  deliveryKey,
  deliveryWord,
  domainName,
  mergeSources,
  shortType,
  subscriberName,
} from "./format";
import { BusSourcesNote, NativeSelect, ScrollRegion } from "./parts";

const STATUSES: readonly BusDeliveryStatus[] = ["dead", "pending", "in_flight", "delivered"];
const PAGE = 50;

export interface DeliveriesViewProps {
  /** `dlq` — только `dead`, без фильтра статуса */
  mode: "all" | "dlq";
  subscribers: readonly string[];
  selectedKey: string | null;
  onOpen: (delivery: BusDelivery) => void;
}

/** Начало дня `YYYY-MM-DD` в часовом поясе браузера → ISO; `to` — начало следующего дня (период включительно). */
function dayStart(value: string, nextDay = false): string | undefined {
  if (!value) return undefined;
  const date = new Date(`${value}T00:00:00`);
  if (Number.isNaN(date.getTime())) return undefined;
  if (nextDay) date.setDate(date.getDate() + 1);
  return date.toISOString();
}

function useDebounced(value: string, ms = 300): string {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = window.setTimeout(() => {
      setDebounced(value);
    }, ms);
    return () => {
      window.clearTimeout(timer);
    };
  }, [value, ms]);
  return debounced;
}

/** Доставки событий всех доменов с фильтрами (домен, статус, подписчик, тип, период) и «Показать ещё». */
export function DeliveriesView({ mode, subscribers, selectedKey, onOpen }: DeliveriesViewProps) {
  const { t } = useTranslation("bus");
  const { date, number } = useFormat();
  const { mobile } = useViewport();
  const [domain, setDomain] = useState<BusDomain | "all">("all");
  const [status, setStatus] = useState<BusDeliveryStatus | "all">("all");
  const [subscriber, setSubscriber] = useState<string>("all");
  const [type, setType] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const typeQuery = useDebounced(type.trim());

  const params = useMemo<ListBusDeliveriesParams>(() => {
    const p: ListBusDeliveriesParams = { limit: PAGE };
    if (domain !== "all") p.domain = domain;
    if (mode === "dlq") p.status = "dead";
    else if (status !== "all") p.status = status;
    if (subscriber !== "all") p.subscriber = subscriber;
    if (typeQuery) p.type = typeQuery;
    const fromIso = dayStart(from);
    const toIso = dayStart(to, true);
    if (fromIso) p.from = fromIso;
    if (toIso) p.to = toIso;
    return p;
  }, [domain, mode, status, subscriber, typeQuery, from, to]);

  const query = useInfiniteQuery({
    queryKey: getListBusDeliveriesQueryKey(params),
    queryFn: ({ pageParam }) =>
      listBusDeliveries(pageParam ? { ...params, cursor: pageParam } : params),
    initialPageParam: "",
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });
  const items = query.data?.pages.flatMap((page) => page.items) ?? [];
  const sources = mergeSources(query.data?.pages ?? []);
  const caption = t(mode === "dlq" ? "deliveries.dlqCaption" : "deliveries.caption");
  const filtered =
    domain !== "all" || status !== "all" || subscriber !== "all" || type !== "" || from || to;
  const id = (name: string) => `pf-bus-${mode}-${name}`;

  const reset = () => {
    setDomain("all");
    setStatus("all");
    setSubscriber("all");
    setType("");
    setFrom("");
    setTo("");
  };

  const more = query.hasNextPage ? (
    <div className="pf-bus-more">
      <Button
        loading={query.isFetchingNextPage}
        onClick={() => {
          void query.fetchNextPage();
        }}
      >
        {t("deliveries.more")}
      </Button>
    </div>
  ) : null;

  let body;
  if (query.isPending) {
    body = <Skeleton active paragraph={{ rows: 6 }} title={false} style={{ padding: 24 }} />;
  } else if (query.isError) {
    body = (
      <EmptyState
        level={3}
        title={t("loadError.title")}
        text={busErrorText(t, query.error)}
        action={
          <Button
            onClick={() => {
              void query.refetch();
            }}
          >
            {t("loadError.retry")}
          </Button>
        }
      />
    );
  } else if (items.length === 0) {
    const empty = mode === "dlq" && !filtered ? "deliveries.dlqEmpty" : "deliveries.empty";
    body = (
      <EmptyState
        level={3}
        title={t(`${empty}.title`)}
        text={t(`${empty}.text`)}
        action={filtered ? <Button onClick={reset}>{t("filters.reset")}</Button> : undefined}
      />
    );
  } else if (mobile) {
    body = (
      <>
        <ul className="pf-bus-list" aria-label={caption}>
          {items.map((d) => {
            const word = deliveryWord(d);
            const selected = deliveryKey(d) === selectedKey;
            return (
              <li key={deliveryKey(d)} data-selected={selected}>
                <div className="pf-bus-list-head">
                  <button
                    type="button"
                    className="pf-bus-link"
                    aria-current={selected ? "true" : undefined}
                    aria-label={t("deliveries.open", {
                      event: shortType(d.event_type),
                      subscriber: subscriberName(t, d.subscriber),
                    })}
                    onClick={() => {
                      onOpen(d);
                    }}
                  >
                    {shortType(d.event_type)}
                  </button>
                  <StatusTag tone={DELIVERY_TONE[word]}>{t(`delivery.${word}`)}</StatusTag>
                </div>
                <span className="pf-hint">
                  {t("deliveries.line", {
                    time: date(d.created_at, "datetime"),
                    domain: domainName(t, d.domain),
                    subscriber: subscriberName(t, d.subscriber),
                    attempts: number(d.attempts),
                  })}
                </span>
                {d.last_error ? <span className="pf-bus-error">{d.last_error}</span> : null}
              </li>
            );
          })}
        </ul>
        {more}
      </>
    );
  } else {
    body = (
      <ScrollRegion label={caption}>
        <Table<BusDelivery>
          rowKey={(d) => deliveryKey(d)}
          dataSource={items}
          pagination={false}
          size="middle"
          aria-label={caption}
          rowClassName={(d) => (deliveryKey(d) === selectedKey ? "pf-bus-row-selected" : "")}
          columns={[
            {
              title: t("deliveries.columns.time"),
              key: "time",
              render: (_, d) => <span className="pf-num">{date(d.created_at, "datetime")}</span>,
            },
            {
              title: t("deliveries.columns.domain"),
              key: "domain",
              render: (_, d) => domainName(t, d.domain),
            },
            {
              title: t("deliveries.columns.event"),
              key: "event",
              render: (_, d) => (
                <div className="pf-bus-cell-stack">
                  <button
                    type="button"
                    className="pf-bus-link"
                    aria-current={deliveryKey(d) === selectedKey ? "true" : undefined}
                    aria-label={t("deliveries.open", {
                      event: shortType(d.event_type),
                      subscriber: subscriberName(t, d.subscriber),
                    })}
                    onClick={() => {
                      onOpen(d);
                    }}
                  >
                    {shortType(d.event_type)}
                  </button>
                  {d.subject ? <span className="pf-hint pf-bus-break">{d.subject}</span> : null}
                </div>
              ),
            },
            {
              title: t("deliveries.columns.subscriber"),
              key: "subscriber",
              render: (_, d) => subscriberName(t, d.subscriber),
            },
            {
              title: t("deliveries.columns.status"),
              key: "status",
              render: (_, d) => {
                const word = deliveryWord(d);
                return <StatusTag tone={DELIVERY_TONE[word]}>{t(`delivery.${word}`)}</StatusTag>;
              },
            },
            {
              title: t("deliveries.columns.attempts"),
              key: "attempts",
              align: "right",
              render: (_, d) => <span className="pf-num">{number(d.attempts)}</span>,
            },
            {
              title: t("deliveries.columns.answer"),
              key: "answer",
              render: (_, d) => <span className="pf-bus-error">{d.last_error ?? "—"}</span>,
            },
          ]}
        />
        {more}
      </ScrollRegion>
    );
  }

  return (
    <div className="pf-bus-stack">
      {mode === "dlq" ? <p className="pf-bus-lead">{t("deliveries.dlqHint")}</p> : null}
      <BusSourcesNote
        sources={sources}
        onRetry={() => {
          void query.refetch();
        }}
      />
      <Card styles={{ body: { padding: 0 } }}>
        <div className="pf-bus-filters" role="group" aria-label={t("filters.label")}>
          <div className="pf-bus-field">
            <label htmlFor={id("domain")}>{t("filters.domain")}</label>
            <NativeSelect<BusDomain | "all">
              id={id("domain")}
              value={domain}
              onChange={setDomain}
              options={[
                { value: "all", label: t("filters.allDomains") },
                ...DOMAINS.map((d) => ({ value: d, label: domainName(t, d) })),
              ]}
            />
          </div>
          {mode === "all" ? (
            <div className="pf-bus-field">
              <label htmlFor={id("status")}>{t("filters.status")}</label>
              <NativeSelect<BusDeliveryStatus | "all">
                id={id("status")}
                value={status}
                onChange={setStatus}
                options={[
                  { value: "all", label: t("filters.allStatuses") },
                  ...STATUSES.map((s) => ({ value: s, label: t(`delivery.${s}`) })),
                ]}
              />
            </div>
          ) : null}
          <div className="pf-bus-field">
            <label htmlFor={id("subscriber")}>{t("filters.subscriber")}</label>
            <NativeSelect<string>
              id={id("subscriber")}
              value={subscriber}
              onChange={setSubscriber}
              options={[
                { value: "all", label: t("filters.allSubscribers") },
                ...subscribers.map((s) => ({ value: s, label: subscriberName(t, s) })),
              ]}
            />
          </div>
          <div className="pf-bus-field">
            <label htmlFor={id("type")}>{t("filters.type")}</label>
            <Input
              id={id("type")}
              value={type}
              maxLength={200}
              allowClear
              placeholder={t("filters.typePlaceholder")}
              style={{ width: 200 }}
              onChange={(event) => {
                setType(event.target.value);
              }}
            />
          </div>
          <div className="pf-bus-field">
            <label htmlFor={id("from")}>{t("filters.from")}</label>
            <Input
              id={id("from")}
              type="date"
              value={from}
              style={{ width: 150 }}
              onChange={(event) => {
                setFrom(event.target.value);
              }}
            />
          </div>
          <div className="pf-bus-field">
            <label htmlFor={id("to")}>{t("filters.to")}</label>
            <Input
              id={id("to")}
              type="date"
              value={to}
              style={{ width: 150 }}
              onChange={(event) => {
                setTo(event.target.value);
              }}
            />
          </div>
          {filtered ? (
            <Button type="link" onClick={reset} className="pf-bus-reset">
              {t("filters.reset")}
            </Button>
          ) : null}
        </div>
        {body}
      </Card>
    </div>
  );
}
