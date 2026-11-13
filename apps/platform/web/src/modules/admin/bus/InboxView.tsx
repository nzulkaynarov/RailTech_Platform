import { useInfiniteQuery } from "@tanstack/react-query";
import { Button, Card } from "antd";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { useViewport } from "../../../app/shell/useViewport";
import type {
  BusDomain,
  BusInboxEntry,
  ListBusInboxParams,
} from "../../../shared/api/generated/model";
import { getListBusInboxQueryKey, listBusInbox } from "../../../shared/api/generated/platform-bff";
import { useFormat } from "../../../shared/lib/useFormat";
import { useShownKey } from "../../../shared/lib/useShownKey";
import { DataBlock, ListSkeleton } from "../../../shared/ui/DataBlock";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { StatusTag } from "../../../shared/ui/StatusTag";
import {
  DOMAINS,
  busErrorText,
  domainName,
  mergeSources,
  inboxKey,
  inboxWord,
  shortType,
  subscriberName,
} from "./format";
import { BusSourcesNote, FilterSelect } from "./parts";
import { DataTable } from "../../../shared/ui/DataTable/DataTable";

const PAGE = 50;

export interface InboxViewProps {
  selectedKey: string | null;
  onOpen: (entry: BusInboxEntry) => void;
}

/** Принятые доменами события, обработка которых упала или ждёт автоповтора (`errors=true`). */
export function InboxView({ selectedKey, onOpen }: InboxViewProps) {
  const { t } = useTranslation("bus");
  const { date, number } = useFormat();
  const { mobile } = useViewport();
  const [domain, setDomain] = useState<BusDomain | "all">("all");
  const params = useMemo<ListBusInboxParams>(
    () => ({ errors: true, limit: PAGE, ...(domain !== "all" ? { domain } : {}) }),
    [domain],
  );
  const query = useInfiniteQuery({
    queryKey: getListBusInboxQueryKey(params),
    queryFn: ({ pageParam }) => listBusInbox(pageParam ? { ...params, cursor: pageParam } : params),
    initialPageParam: "",
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });
  const items = query.data?.pages.flatMap((page) => page.items) ?? [];
  const sources = mergeSources(query.data?.pages ?? []);
  const caption = t("inboxView.caption");

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

  const shownKey = useShownKey(getListBusInboxQueryKey(params), query.isPlaceholderData);
  let body;
  if (query.isPending) {
    body = <ListSkeleton rows={PAGE} />;
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
    body = (
      <EmptyState
        level={3}
        title={t("inboxView.empty.title")}
        text={t("inboxView.empty.text")}
        action={
          domain !== "all" ? (
            <Button
              onClick={() => {
                setDomain("all");
              }}
            >
              {t("filters.reset")}
            </Button>
          ) : undefined
        }
      />
    );
  } else if (mobile) {
    body = (
      <>
        <ul className="pf-bus-list" aria-label={caption}>
          {items.map((e) => {
            const word = inboxWord(e);
            const selected = inboxKey(e) === selectedKey;
            return (
              <li key={inboxKey(e)} data-selected={selected}>
                <div className="pf-bus-list-head">
                  <button
                    type="button"
                    className="pf-bus-link"
                    aria-current={selected ? "true" : undefined}
                    aria-label={t("inboxView.open", {
                      event: shortType(e.type),
                      domain: domainName(t, e.domain),
                    })}
                    onClick={() => {
                      onOpen(e);
                    }}
                  >
                    {shortType(e.type)}
                  </button>
                  <StatusTag kind="busInbox" status={word}>
                    {t(`inbox.${word}`)}
                  </StatusTag>
                </div>
                <span className="pf-hint">
                  {t("inboxView.line", {
                    time: date(e.received_at, "datetime"),
                    publisher: subscriberName(t, e.publisher),
                    domain: domainName(t, e.domain),
                    attempts: number(e.attempts),
                  })}
                </span>
                {e.error ? <span className="pf-bus-error">{e.error}</span> : null}
              </li>
            );
          })}
        </ul>
        {more}
      </>
    );
  } else {
    body = (
      <>
        <DataTable<BusInboxEntry>
          tableId="admin.bus.inbox"
          caption={caption}
          scrollLabel={caption}
          rows={items}
          rowKey={inboxKey}
          rowAttrs={(row) => ({
            className: inboxKey(row) === selectedKey ? "pf-bus-row-selected" : "",
          })}
          columns={[
            {
              id: "time",
              header: t("inboxView.columns.time"),
              width: null,
              cell: (e) => <span className="pf-num">{date(e.received_at, "datetime")}</span>,
            },
            {
              id: "domain",
              header: t("inboxView.columns.domain"),
              width: null,
              cell: (e) => domainName(t, e.domain),
            },
            {
              id: "event",
              header: t("inboxView.columns.event"),
              width: null,
              cell: (e) => (
                <div className="pf-bus-cell-stack">
                  <button
                    type="button"
                    className="pf-bus-link"
                    aria-current={inboxKey(e) === selectedKey ? "true" : undefined}
                    aria-label={t("inboxView.open", {
                      event: shortType(e.type),
                      domain: domainName(t, e.domain),
                    })}
                    onClick={() => {
                      onOpen(e);
                    }}
                  >
                    {shortType(e.type)}
                  </button>
                  {e.subject ? <span className="pf-hint pf-bus-break">{e.subject}</span> : null}
                </div>
              ),
            },
            {
              id: "publisher",
              header: t("inboxView.columns.publisher"),
              width: null,
              cell: (e) => subscriberName(t, e.publisher),
            },
            {
              id: "status",
              header: t("inboxView.columns.status"),
              width: null,
              cell: (e) => {
                const word = inboxWord(e);
                return (
                  <StatusTag kind="busInbox" status={word}>
                    {t(`inbox.${word}`)}
                  </StatusTag>
                );
              },
            },
            {
              id: "attempts",
              header: t("inboxView.columns.attempts"),
              width: null,
              numeric: true,
              cell: (e) => <span className="pf-num">{number(e.attempts)}</span>,
            },
            {
              id: "error",
              header: t("inboxView.columns.error"),
              width: null,
              cell: (e) => <span className="pf-bus-error">{e.error ?? "—"}</span>,
            },
          ]}
        />
        {more}
      </>
    );
  }

  return (
    <div className="pf-bus-stack">
      <p className="pf-bus-lead">{t("inboxView.hint")}</p>
      <BusSourcesNote
        sources={sources}
        onRetry={() => {
          void query.refetch();
        }}
      />
      <Card styles={{ body: { padding: 0 } }}>
        <div className="pf-bus-filters" role="group" aria-label={t("filters.label")}>
          <div className="pf-bus-field">
            <label htmlFor="pf-bus-inbox-domain">{t("filters.domain")}</label>
            <FilterSelect<BusDomain | "all">
              id="pf-bus-inbox-domain"
              value={domain}
              onChange={setDomain}
              options={[
                { value: "all", label: t("filters.allDomains") },
                ...DOMAINS.map((d) => ({ value: d, label: domainName(t, d) })),
              ]}
            />
          </div>
        </div>
        <DataBlock busy={query.isPlaceholderData} resetKey={shownKey}>
          {body}
        </DataBlock>
      </Card>
    </div>
  );
}
