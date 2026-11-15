import { Alert, Button, Drawer, Input, Select, Skeleton } from "antd";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import type { SentMail as SentMailRow, SentMailStatus } from "../../../shared/api/generated/model";
import { useGetSentMailBody, useListSentMail } from "../../../shared/api/generated/platform-bff";
import { useFormat } from "../../../shared/lib/useFormat";
import { DataTable, type DataColumn } from "../../../shared/ui/DataTable/DataTable";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { StatusTag } from "../../../shared/ui/StatusTag";

const STATUSES: SentMailStatus[] = ["sent", "queued", "failed", "skipped_no_smtp"];

/**
 * «Почта · Отправленные» (план 2.8, MAIL-1): письма, отправленные по вашему запросу (администратору — все), поиск по
 * адресату и теме, статус доставки; текст открывается по нажатию — его просмотр попадает в журнал аудита.
 */
export function SentMail() {
  const { t } = useTranslation("letters");
  const { date } = useFormat();
  const [search, setSearch] = useState("");
  const [q, setQ] = useState("");
  const [status, setStatus] = useState<SentMailStatus | undefined>();
  const [cursor, setCursor] = useState<string | undefined>();
  const [open, setOpen] = useState<SentMailRow | null>(null);
  useEffect(() => {
    const timer = window.setTimeout(() => {
      setQ(search.trim());
      setCursor(undefined);
    }, 300);
    return () => {
      window.clearTimeout(timer);
    };
  }, [search]);
  const query = useListSentMail({
    ...(q ? { q } : {}),
    ...(status ? { status } : {}),
    ...(cursor ? { cursor } : {}),
  });

  const columns: DataColumn<SentMailRow>[] = [
    {
      id: "created",
      header: t("mail.sent.columns.date"),
      width: 150,
      cell: (row) => date(row.created_at, "datetime"),
    },
    {
      id: "to",
      header: t("mail.sent.columns.to"),
      width: 220,
      cellClassName: "pf-ell",
      cellTitle: (row) => row.to,
      cell: (row) => row.to,
    },
    {
      id: "subject",
      header: t("mail.sent.columns.subject"),
      width: null,
      cellClassName: "pf-ell",
      cellTitle: (row) => row.subject,
      cell: (row) => (
        <Button
          type="link"
          className="pf-co-link"
          onClick={() => {
            setOpen(row);
          }}
        >
          {row.subject}
        </Button>
      ),
    },
    {
      id: "status",
      header: t("mail.sent.columns.status"),
      width: 150,
      cell: (row) => (
        <StatusTag kind="mail" status={row.status} title={row.error ?? undefined}>
          {t(`mail.sent.status.${row.status}`)}
        </StatusTag>
      ),
    },
    {
      id: "by",
      header: t("mail.sent.columns.by"),
      width: 180,
      cellClassName: "pf-ell",
      cell: (row) => row.requested_by ?? "—",
    },
  ];

  let body;
  if (query.isPending) body = <Skeleton active paragraph={{ rows: 6 }} />;
  else if (query.isError) {
    body = <EmptyState title={t("state.loadError.title")} text={t("state.loadError.text")} />;
  } else if (query.data.items.length === 0) {
    body = (
      <EmptyState
        title={t("mail.sent.emptyTitle")}
        text={q || status ? t("mail.sent.emptySearch") : t("mail.sent.emptyText")}
      />
    );
  } else {
    body = (
      <>
        <DataTable
          tableId="eds.mail.sent"
          caption={t("mail.sent.caption")}
          scrollLabel={t("mail.sent.scroll")}
          flexMin={220}
          columns={columns}
          rows={query.data.items}
          rowKey={(row) => row.id}
        />
        {query.data.next_cursor || cursor ? (
          <div className="pf-mail-tools">
            {cursor ? (
              <Button
                onClick={() => {
                  setCursor(undefined);
                }}
              >
                {t("mail.sent.first")}
              </Button>
            ) : null}
            {query.data.next_cursor ? (
              <Button
                onClick={() => {
                  setCursor(query.data.next_cursor ?? undefined);
                }}
              >
                {t("mail.sent.more")}
              </Button>
            ) : null}
          </div>
        ) : null}
      </>
    );
  }

  return (
    <div className="pf-mail-body">
      <div className="pf-mail-tools">
        <Input.Search
          allowClear
          className="pf-mail-search"
          aria-label={t("mail.sent.search")}
          placeholder={t("mail.sent.searchHint")}
          value={search}
          onChange={(event) => {
            setSearch(event.target.value);
          }}
        />
        <Select
          allowClear
          aria-label={t("mail.sent.statusFilter")}
          placeholder={t("mail.sent.statusAll")}
          style={{ minWidth: 180 }}
          value={status}
          onChange={(value: SentMailStatus | undefined) => {
            setStatus(value);
            setCursor(undefined);
          }}
          options={STATUSES.map((value) => ({ value, label: t(`mail.sent.status.${value}`) }))}
        />
      </div>
      {body}
      {open ? (
        <SentMailDrawer
          row={open}
          onClose={() => {
            setOpen(null);
          }}
        />
      ) : null}
    </div>
  );
}

function SentMailDrawer({ row, onClose }: { row: SentMailRow; onClose: () => void }) {
  const { t } = useTranslation("letters");
  const body = useGetSentMailBody(Number(row.id));
  return (
    <Drawer open width={560} title={row.subject} onClose={onClose} destroyOnHidden>
      <p className="pf-hint">{t("mail.sent.to", { to: row.to })}</p>
      {row.error ? <Alert type="error" showIcon message={row.error} /> : null}
      {row.path ? <Link to={row.path}>{t("mail.sent.openDocument")}</Link> : null}
      {body.isPending ? (
        <Skeleton active paragraph={{ rows: 4 }} />
      ) : body.data?.text ? (
        <pre className="pf-mail-sent-text">{body.data.text}</pre>
      ) : (
        <p className="pf-hint">{t("mail.sent.noText")}</p>
      )}
      {body.data && body.data.attachments.length > 0 ? (
        <p className="pf-hint">
          {t("mail.sent.attachments", { names: body.data.attachments.join(", ") })}
        </p>
      ) : null}
    </Drawer>
  );
}
