import { useInfiniteQuery } from "@tanstack/react-query";
import { Button, Card, Skeleton, Table } from "antd";
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
import { EmptyState } from "../../../shared/ui/EmptyState";
import { StatusTag } from "../../../shared/ui/StatusTag";
import {
  DOMAINS,
  INBOX_TONE,
  busErrorText,
  domainName,
  inboxKey,
  inboxWord,
  shortType,
  subscriberName,
} from "./format";
import { BusSourcesNote, NativeSelect, ScrollRegion } from "./parts";

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
  const sources = query.data?.pages[query.data.pages.length - 1]?.sources;
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

  let body;
  if (query.isPending) {
    body = <Skeleton active paragraph={{ rows: 4 }} title={false} style={{ padding: 24 }} />;
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
                  <StatusTag tone={INBOX_TONE[word]}>{t(`inbox.${word}`)}</StatusTag>
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
      <ScrollRegion label={caption}>
        <Table<BusInboxEntry>
          rowKey={(e) => inboxKey(e)}
          dataSource={items}
          pagination={false}
          size="middle"
          aria-label={caption}
          rowClassName={(e) => (inboxKey(e) === selectedKey ? "pf-bus-row-selected" : "")}
          columns={[
            {
              title: t("inboxView.columns.time"),
              key: "time",
              render: (_, e) => <span className="pf-num">{date(e.received_at, "datetime")}</span>,
            },
            {
              title: t("inboxView.columns.domain"),
              key: "domain",
              render: (_, e) => domainName(t, e.domain),
            },
            {
              title: t("inboxView.columns.event"),
              key: "event",
              render: (_, e) => (
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
              title: t("inboxView.columns.publisher"),
              key: "publisher",
              render: (_, e) => subscriberName(t, e.publisher),
            },
            {
              title: t("inboxView.columns.status"),
              key: "status",
              render: (_, e) => {
                const word = inboxWord(e);
                return <StatusTag tone={INBOX_TONE[word]}>{t(`inbox.${word}`)}</StatusTag>;
              },
            },
            {
              title: t("inboxView.columns.attempts"),
              key: "attempts",
              align: "right",
              render: (_, e) => <span className="pf-num">{number(e.attempts)}</span>,
            },
            {
              title: t("inboxView.columns.error"),
              key: "error",
              render: (_, e) => <span className="pf-bus-error">{e.error ?? "—"}</span>,
            },
          ]}
        />
        {more}
      </ScrollRegion>
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
            <NativeSelect<BusDomain | "all">
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
        {body}
      </Card>
    </div>
  );
}
