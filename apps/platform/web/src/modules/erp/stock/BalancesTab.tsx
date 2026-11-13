import { Button, Card, Checkbox, Input } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { useViewport } from "../../../app/shell/useViewport";
import type { StockRow } from "../../../shared/api/generated/model";
import { useListStockBalances } from "../../../shared/api/generated/platform-bff";
import { useFormat } from "../../../shared/lib/useFormat";
import { DataTable, type DataColumn } from "../../../shared/ui/DataTable/DataTable";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { QueryState } from "../../../shared/ui/FormParts";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { useStateLabels } from "./api";
import { ProductDrawer } from "./ProductDrawer";

/** Ширины колонок: номенклатура (гибкая), на складе, резерв, свободно, в пути, ячейки (UX-1c, S9) */
const COLS = {
  onHand: 120,
  reserved: 100,
  free: 140,
  incoming: 160,
  cells: 160,
};

function Incoming({ row }: { row: StockRow }) {
  const { t } = useTranslation("stock");
  const { date } = useFormat();
  if (row.incoming === 0) return <span className="pf-hint">—</span>;
  return (
    <span>
      <span className="pf-num">+{row.incoming}</span>
      {row.next_expected ? (
        <span className="pf-hint"> · {t("balances.until", { date: date(row.next_expected) })}</span>
      ) : null}
    </span>
  );
}

function Cells({ row }: { row: StockRow }) {
  const { t } = useTranslation("stock");
  if (row.cells.length === 0) return <span className="pf-hint">—</span>;
  return (
    <span>
      {row.cells
        .map((c) =>
          c.cell ? t("balances.cellLine", { cell: c.cell, count: c.on_hand }) : String(c.on_hand),
        )
        .join(" · ")}
    </span>
  );
}

function Free({ row }: { row: StockRow }) {
  const { t } = useTranslation("stock");
  return row.free > 0 ? (
    <StatusTag kind="stock" status="free">
      {t("balances.free", { count: row.free })}
    </StatusTag>
  ) : (
    <StatusTag kind="stock" status="none">
      {t("balances.noFree")}
    </StatusTag>
  );
}

function Rows({ items, onOpen }: { items: readonly StockRow[]; onOpen: (row: StockRow) => void }) {
  const { t } = useTranslation("stock");
  const { mobile } = useViewport();
  if (mobile) {
    return (
      <ul className="pf-calc-cards" aria-label={t("balances.caption")}>
        {items.map((row) => (
          <li key={row.product_id}>
            <div className="pf-calc-card-head">
              <Button
                type="link"
                className="pf-calc-link"
                onClick={() => {
                  onOpen(row);
                }}
              >
                {row.name}
              </Button>
              <Free row={row} />
            </div>
            <p className="pf-hint">
              {t("balances.card", { onHand: row.on_hand, reserved: row.reserved })}
            </p>
            <p className="pf-hint">
              <Cells row={row} />
            </p>
          </li>
        ))}
      </ul>
    );
  }
  // Ширины по типу (COLS, T1); остальное — настройка сотрудника в «Столбцах» (пункт «Т»).
  const columns: DataColumn<StockRow>[] = [
    {
      id: "product",
      header: t("balances.columns.product"),
      width: null,
      cell: (row) => (
        <>
          <Button
            type="link"
            className="pf-calc-link"
            aria-label={t("balances.open", { name: row.name })}
            onClick={() => {
              onOpen(row);
            }}
          >
            {row.name}
          </Button>
          <div className="pf-hint pf-num">{row.article}</div>
        </>
      ),
    },
    {
      id: "onHand",
      header: t("balances.columns.onHand"),
      width: COLS.onHand,
      numeric: true,
      cell: (row) => (
        <>
          {row.on_hand} <span className="pf-hint">{row.unit}</span>
        </>
      ),
    },
    {
      id: "reserved",
      header: t("balances.columns.reserved"),
      width: COLS.reserved,
      numeric: true,
      cell: (row) => row.reserved,
    },
    {
      id: "free",
      header: t("balances.columns.free"),
      width: COLS.free,
      cell: (row) => (
        <>
          <Free row={row} />
        </>
      ),
    },
    {
      id: "incoming",
      header: t("balances.columns.incoming"),
      width: COLS.incoming,
      cell: (row) => (
        <>
          <Incoming row={row} />
        </>
      ),
    },
    {
      id: "cells",
      header: t("balances.columns.cells"),
      width: COLS.cells,
      cell: (row) => (
        <>
          <Cells row={row} />
        </>
      ),
    },
  ];
  return (
    <DataTable
      tableId="erp.stock.balances"
      caption={t("balances.caption")}
      scrollLabel={t("balances.scroll")}
      className="pf-calc-table"
      flexMin={240}
      columns={columns}
      rows={items}
      rowKey={(row) => row.product_id}
    />
  );
}

/** Вкладка «Остатки и резервы»: номенклатура с остатком, резервом, свободным остатком, ожидаемым приходом и ячейками. */
export function BalancesTab() {
  const { t } = useTranslation("stock");
  const labels = useStateLabels();
  const [q, setQ] = useState("");
  const [reservedOnly, setReservedOnly] = useState(false);
  const [open, setOpen] = useState<StockRow | null>(null);
  const query = useListStockBalances({
    ...(q.trim() ? { q: q.trim() } : {}),
    ...(reservedOnly ? { only: "reserved" as const } : {}),
  });
  return (
    <>
      <Card styles={{ body: { padding: 0 } }}>
        <div className="pf-stock-toolbar">
          <Input.Search
            allowClear
            aria-label={t("balances.search")}
            placeholder={t("balances.search")}
            onSearch={setQ}
            className="pf-stock-search"
          />
          <Checkbox
            checked={reservedOnly}
            onChange={(event) => {
              setReservedOnly(event.target.checked);
            }}
          >
            {t("balances.only")}
          </Checkbox>
        </div>
        <QueryState query={query} labels={labels} rows={10}>
          {(data) =>
            data.items.length === 0 ? (
              <EmptyState
                title={t(q ? "balances.emptySearch.title" : "balances.empty.title")}
                text={t(q ? "balances.emptySearch.text" : "balances.empty.text")}
              />
            ) : (
              <Rows items={data.items} onOpen={setOpen} />
            )
          }
        </QueryState>
      </Card>
      {open ? (
        <ProductDrawer
          row={open}
          onClose={() => {
            setOpen(null);
          }}
        />
      ) : null}
    </>
  );
}
