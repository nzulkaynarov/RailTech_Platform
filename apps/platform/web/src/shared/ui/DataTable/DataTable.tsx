import {
  type Column,
  type ColumnDef,
  type RowData,
  columnOrderingFeature,
  columnPinningFeature,
  columnSizingFeature,
  columnVisibilityFeature,
  tableFeatures,
  useTable,
} from "@tanstack/react-table";
import {
  type HTMLAttributes,
  type PointerEvent,
  type ReactNode,
  useCallback,
  useContext,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useTranslation } from "react-i18next";

import { AuthContext } from "../../../app/auth/useAuth";
import { TableCols } from "../DataBlock";
import { ScrollRegion } from "../FormParts";
import { tableMinWidth } from "../tableWidth";
import { ColumnsMenu } from "./ColumnsMenu";
import { type TableSettings, tableKey, useTablesStore } from "./tableSettings";

import "./data-table.css";

/**
 * Столбец рабочего списка. Ширина по умолчанию — по типу столбца (platform-frontend.md §4.2), `null` — гибкий (делит
 * остаток). Сотрудник меняет ширину, видимость, порядок и закрепление сам (`DataTable`).
 */
export interface DataColumn<Row> {
  id: string;
  /** Заголовок; он же — подпись в «Столбцах» */
  header: string;
  /** Заголовок только для экранного чтеца (столбец кнопки строки) */
  headerHidden?: boolean;
  width: number | null;
  /** Пределы ручной ширины, px */
  minWidth?: number;
  maxWidth?: number;
  /** Число: заголовок и ячейка вправо (`pf-col-num`) */
  numeric?: boolean;
  cellClassName?: string;
  cell: (row: Row) => ReactNode;
  /** Подсказка ячейки (полный текст обрезанного) */
  cellTitle?: (row: Row) => string | undefined;
  /** Можно ли скрыть; первый столбец (номер или название) скрыть нельзя никогда */
  hideable?: boolean;
}

export interface DataTableProps<Row> {
  /** Идентификатор таблицы для настроек сотрудника, например `eds.documents` */
  tableId: string;
  caption: string;
  scrollLabel: string;
  columns: readonly DataColumn<Row>[];
  rows: readonly Row[];
  rowKey: (row: Row) => string;
  rowAttrs?: (row: Row) => HTMLAttributes<HTMLTableRowElement> & Record<`data-${string}`, unknown>;
  className?: string;
  /** Минимум гибкого столбца, px: ниже суммы таблица прокручивается в своей области */
  flexMin?: number;
}

const features = tableFeatures({
  columnVisibilityFeature,
  columnOrderingFeature,
  columnPinningFeature,
  columnSizingFeature,
});

const DEFAULT_MIN = 64;
const DEFAULT_MAX = 640;
/** Шаг ширины с клавиатуры (стрелки на ручке), px */
const KEY_STEP = 16;
const EMPTY: TableSettings = {};

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, Math.round(value)));
}

/**
 * Таблица рабочего списка (пункт «Т», ресёрч 2026-11-02 «Таблицы» §4.2): наша разметка (`table-layout: fixed`,
 * `<colgroup>`, `caption`, область прокрутки), состояние столбцов — TanStack Table. Ширина по умолчанию — по типу; ручная
 * (мышь, стрелки на ручке, двойной щелчок — по содержимому) меняется только действием сотрудника, поэтому столбцы стоят на
 * месте при смене фильтра и страницы (инвариант 6). «Столбцы» — видимость, порядок, закрепление слева, «Сбросить».
 */
export function DataTable<Row extends RowData>({
  tableId,
  caption,
  scrollLabel,
  columns,
  rows,
  rowKey,
  rowAttrs,
  className,
  flexMin = 170,
}: DataTableProps<Row>) {
  const { t } = useTranslation("ui");
  const userId = useContext(AuthContext)?.me.id ?? "-";
  const key = tableKey(userId, tableId);
  const saved = useTablesStore((state) => state.entries[key]) ?? EMPTY;
  const update = useTablesStore((state) => state.update);
  const reset = useTablesStore((state) => state.reset);
  const byId = useMemo(() => new Map(columns.map((column) => [column.id, column])), [columns]);
  const firstId = columns[0]?.id;

  const defs = useMemo<ColumnDef<typeof features, Row>[]>(
    () =>
      columns.map((column) => ({
        id: column.id,
        header: column.header,
        accessorFn: (row: Row) => row,
        size: column.width ?? flexMin,
        minSize: column.minWidth ?? DEFAULT_MIN,
        maxSize: column.maxWidth ?? DEFAULT_MAX,
        enableHiding: column.id !== firstId && column.hideable !== false,
      })),
    [columns, firstId, flexMin],
  );

  // Настройки сотрудника — только для столбцов, которые есть на экране сейчас (другая вкладка может их не иметь).
  const state = useMemo(() => {
    const known = (id: string) => byId.has(id);
    const order = (saved.order ?? []).filter(known);
    const fullOrder = [...order, ...columns.map((c) => c.id).filter((id) => !order.includes(id))];
    const hidden = (saved.hidden ?? []).filter((id) => known(id) && id !== firstId);
    const pinned = (saved.pinned ?? []).filter(known);
    const sizing = Object.fromEntries(
      Object.entries(saved.sizing ?? {}).filter(([id]) => known(id)),
    );
    return {
      columnOrder: fullOrder,
      columnVisibility: Object.fromEntries(hidden.map((id) => [id, false])),
      columnPinning: { start: pinned, end: [] },
      columnSizing: sizing,
    };
  }, [saved, byId, columns, firstId]);

  const table = useTable({
    features,
    columns: defs,
    data: rows,
    getRowId: (row: Row) => rowKey(row),
    state,
  });

  const visible = table.getVisibleLeafColumns();
  const ordered = [
    ...visible.filter((column) => column.getIsPinned() === "start"),
    ...visible.filter((column) => column.getIsPinned() !== "start"),
  ];
  const widthOf = (id: string): number | null => {
    const own = state.columnSizing[id];
    if (own !== undefined) return own;
    return byId.get(id)?.width ?? null;
  };
  const widths = ordered.map((column) => widthOf(column.id));

  // Смещения закреплённых столбцов (position: sticky) — по фактической ширине заголовков после отрисовки.
  const tableRef = useRef<HTMLTableElement>(null);
  const [offsets, setOffsets] = useState<Record<string, number>>({});
  const pinnedIds = ordered.filter((c) => c.getIsPinned() === "start").map((c) => c.id);
  const pinnedKey = pinnedIds.join(",");
  const widthKey = widths.join(",");
  useLayoutEffect(() => {
    const element = tableRef.current;
    if (!element || pinnedKey === "") {
      setOffsets((prev) => (Object.keys(prev).length === 0 ? prev : {}));
      return;
    }
    const heads = element.querySelectorAll<HTMLTableCellElement>(":scope > thead > tr > th");
    const next: Record<string, number> = {};
    let left = 0;
    pinnedKey.split(",").forEach((id, index) => {
      next[id] = left;
      left += heads[index]?.getBoundingClientRect().width ?? 0;
    });
    setOffsets((prev) => (JSON.stringify(prev) === JSON.stringify(next) ? prev : next));
  }, [pinnedKey, widthKey]);

  // Ручки ширины — отдельным слоем над заголовком, по правой границе каждого столбца: внутри `<th>` их подпись вошла бы в
  // имя заголовка («Тема Ширина столбца «Тема»»), и экранный чтец повторял бы её на каждой ячейке.
  const [edges, setEdges] = useState<{ id: string; left: number; height: number }[]>([]);
  const orderKey = ordered.map((c) => c.id).join(",");
  useLayoutEffect(() => {
    const element = tableRef.current;
    if (!element) return;
    const measure = () => {
      const head = element.tHead;
      const next = [
        ...element.querySelectorAll<HTMLTableCellElement>(":scope > thead > tr > th"),
      ].map((th) => ({
        id: th.dataset.col ?? "",
        left: th.offsetLeft + th.offsetWidth,
        height: head?.offsetHeight ?? th.offsetHeight,
      }));
      setEdges((prev) => (JSON.stringify(prev) === JSON.stringify(next) ? prev : next));
    };
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => {
      observer.disconnect();
    };
  }, [orderKey, widthKey]);

  const save = useCallback(
    (patch: Partial<TableSettings>) => {
      update(key, patch);
    },
    [key, update],
  );

  const setWidth = useCallback(
    (id: string, width: number) => {
      const column = byId.get(id);
      const value = clamp(width, column?.minWidth ?? DEFAULT_MIN, column?.maxWidth ?? DEFAULT_MAX);
      save({ sizing: { ...state.columnSizing, [id]: value } });
    },
    [byId, save, state.columnSizing],
  );

  const headerCell = (id: string): HTMLTableCellElement | null =>
    tableRef.current?.querySelector<HTMLTableCellElement>(
      `:scope > thead > tr > th[data-col="${CSS.escape(id)}"]`,
    ) ?? null;

  const startDrag = (id: string) => (event: PointerEvent<HTMLDivElement>) => {
    const th = headerCell(id);
    if (!th) return;
    event.preventDefault();
    const handle = event.currentTarget;
    handle.setPointerCapture(event.pointerId);
    const startX = event.clientX;
    const startWidth = th.getBoundingClientRect().width;
    let last = startWidth;
    const move = (e: globalThis.PointerEvent) => {
      last = startWidth + (e.clientX - startX);
      th.style.width = `${String(Math.round(last))}px`;
      const col = tableRef.current?.querySelector<HTMLTableColElement>(
        `:scope > colgroup > col:nth-child(${String(th.cellIndex + 1)})`,
      );
      if (col) col.style.width = `${String(Math.round(last))}px`;
    };
    const end = () => {
      handle.removeEventListener("pointermove", move);
      handle.removeEventListener("pointerup", end);
      handle.removeEventListener("pointercancel", end);
      th.style.width = "";
      setWidth(id, last);
    };
    handle.addEventListener("pointermove", move);
    handle.addEventListener("pointerup", end);
    handle.addEventListener("pointercancel", end);
  };

  /** Двойной щелчок по ручке — ширина по содержимому видимых строк (Fiori, AG Grid). */
  const fit = (id: string) => {
    const th = headerCell(id);
    const element = tableRef.current;
    if (!th || !element) return;
    const index = th.cellIndex;
    let need = th.scrollWidth;
    for (const row of element.querySelectorAll<HTMLTableRowElement>(":scope > tbody > tr")) {
      const cell = row.cells.item(index);
      if (cell) need = Math.max(need, cell.scrollWidth);
    }
    setWidth(id, need + 2);
  };

  /** «Уже» / «Шире» в «Столбцах» — смена ширины с клавиатуры, шагом KEY_STEP. */
  const step = (id: string, delta: number) => {
    const th = headerCell(id);
    const now = widthOf(id) ?? th?.getBoundingClientRect().width ?? flexMin;
    setWidth(id, now + delta * KEY_STEP);
  };

  const stick = (column: Column<typeof features, Row>) =>
    column.getIsPinned() === "start" && column.id in offsets
      ? { position: "sticky" as const, left: offsets[column.id], zIndex: 1 }
      : undefined;

  const lastPinned = pinnedIds.at(-1);

  return (
    <div className="pf-dt">
      <div className="pf-dt-tools">
        <ColumnsMenu
          columns={columns.map((column) => ({
            id: column.id,
            header: column.header,
            canHide: column.id !== firstId && column.hideable !== false,
          }))}
          order={state.columnOrder}
          hidden={Object.keys(state.columnVisibility)}
          pinned={pinnedIds}
          changed={saved !== EMPTY}
          onOrder={(order) => {
            save({ order });
          }}
          onHidden={(hidden) => {
            save({ hidden });
          }}
          onPinned={(pinned) => {
            save({ pinned });
          }}
          onWidth={step}
          onReset={() => {
            reset(key);
          }}
        />
      </div>
      <ScrollRegion label={scrollLabel}>
        <div className="pf-dt-frame">
          <table
            ref={tableRef}
            className={
              className ? `pf-fixed-table pf-dt-table ${className}` : "pf-fixed-table pf-dt-table"
            }
            style={{ minWidth: tableMinWidth(widths, flexMin) }}
          >
            <caption className="pf-sr-only">{caption}</caption>
            <TableCols widths={widths} />
            <thead>
              <tr>
                {ordered.map((column) => {
                  const def = byId.get(column.id);
                  if (!def) return null;
                  return (
                    <th
                      key={column.id}
                      scope="col"
                      data-col={column.id}
                      data-pinned={column.id === lastPinned ? "last" : undefined}
                      className={def.numeric ? "pf-col-num" : undefined}
                      style={stick(column)}
                    >
                      {def.headerHidden ? (
                        <span className="pf-sr-only">{def.header}</span>
                      ) : (
                        def.header
                      )}
                    </th>
                  );
                })}
              </tr>
            </thead>
            <tbody>
              {table.getRowModel().rows.map((row) => {
                const original = row.original;
                return (
                  <tr key={row.id} {...rowAttrs?.(original)}>
                    {ordered.map((column) => {
                      const def = byId.get(column.id);
                      if (!def) return null;
                      const classes = [def.numeric ? "pf-col-num" : "", def.cellClassName ?? ""]
                        .filter(Boolean)
                        .join(" ");
                      return (
                        <td
                          key={column.id}
                          className={classes || undefined}
                          title={def.cellTitle?.(original)}
                          data-pinned={column.id === lastPinned ? "last" : undefined}
                          style={stick(column)}
                        >
                          {def.cell(original)}
                        </td>
                      );
                    })}
                  </tr>
                );
              })}
            </tbody>
          </table>
          {edges.map((edge) => {
            const def = byId.get(edge.id);
            if (!def) return null;
            return (
              <div
                key={edge.id}
                className="pf-dt-resize"
                style={{ left: edge.left - 4, height: edge.height }}
                // только мышь: с клавиатуры ширину меняют «Уже» и «Шире» в «Столбцах» (подпись разделителя с именем
                // столбца путалась бы с полями формы и заголовком)
                aria-hidden="true"
                title={t("table.resize", { name: def.header })}
                onPointerDown={startDrag(edge.id)}
                onDoubleClick={() => {
                  fit(edge.id);
                }}
              />
            );
          })}
        </div>
      </ScrollRegion>
    </div>
  );
}
