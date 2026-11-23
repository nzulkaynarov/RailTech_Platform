import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import "../i18n";
import type { DataColumn } from "./DataTable/DataTable";
import { RegistryTable, type RegistryTableProps } from "./RegistryTable";

interface Item {
  id: string;
  name: string;
}

const ROWS: Item[] = [
  { id: "a", name: "Первый" },
  { id: "b", name: "Второй" },
];
const COLUMNS: DataColumn<Item>[] = [
  { id: "name", header: "Название", width: null, cell: (row) => row.name },
];

function frame(props: Partial<RegistryTableProps<Item>> = {}) {
  return render(
    <RegistryTable<Item>
      tableId="test.registry"
      caption="Записи"
      scrollLabel="Таблица записей"
      columns={COLUMNS}
      rows={ROWS}
      rowKey={(row) => row.id}
      empty={<p>Записей нет</p>}
      {...props}
    />,
  );
}

describe("RegistryTable", () => {
  it("shows the table in a card with the shared look hooks", () => {
    const { container } = frame();
    const table = screen.getByRole("table", { name: "Записи" });
    expect(table).toHaveClass("pf-dt-table");
    expect(container.querySelector(".pf-reg.ant-card")).not.toBeNull();
    expect(screen.getByRole("columnheader", { name: "Название" })).toBeInTheDocument();
  });

  it("loading: a skeleton shaped like the list, no table, no empty text", () => {
    const { container } = frame({ loading: true, rows: [], skeletonRows: 5 });
    expect(container.querySelectorAll("[data-pf-skeleton] .pf-list-skel-row")).toHaveLength(5);
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.queryByText("Записей нет")).toBeNull();
  });

  it("empty: the empty state instead of a headers-only table", () => {
    frame({ rows: [] });
    expect(screen.getByText("Записей нет")).toBeInTheDocument();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("error wins over the rows and over the empty state", () => {
    frame({ error: <p>Не загрузилось</p> });
    expect(screen.getByText("Не загрузилось")).toBeInTheDocument();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("selection: only the row with selectedKey is marked", () => {
    frame({ selectedKey: "b" });
    const rows = screen.getAllByRole("row").slice(1);
    expect(rows.map((row) => row.getAttribute("data-selected"))).toEqual([null, "true"]);
  });

  it("selection: no selectedKey, nothing is marked; own rowAttrs are kept", () => {
    frame({ rowAttrs: (row) => ({ "data-row": row.id }) });
    const rows = screen.getAllByRole("row").slice(1);
    expect(rows.map((row) => row.getAttribute("data-selected"))).toEqual([null, null]);
    expect(rows.map((row) => row.getAttribute("data-row"))).toEqual(["a", "b"]);
  });

  it("the narrow-block list replaces the table", () => {
    frame({
      list: (
        <ul aria-label="Список">
          <li>строка</li>
        </ul>
      ),
    });
    expect(screen.getByRole("list", { name: "Список" })).toBeInTheDocument();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("one pager: summary on the left, page change goes out", () => {
    const onChange = vi.fn();
    frame({
      pagination: {
        current: 1,
        pageSize: 2,
        total: 5,
        onChange,
        label: "Страницы записей",
        summary: "Записей: 5",
      },
    });
    expect(screen.getByText("Записей: 5")).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Страницы записей" })).toBeInTheDocument();
    fireEvent.click(screen.getByTitle("2"));
    expect(onChange).toHaveBeenCalledWith(2, expect.anything());
  });

  it("no pager while loading or when everything fits one page", () => {
    const pagination = { current: 1, pageSize: 50, total: 2, onChange: vi.fn(), label: "Страницы" };
    const { rerender } = frame({ pagination });
    expect(screen.queryByRole("list", { name: "Страницы" })).toBeNull();
    rerender(
      <RegistryTable<Item>
        tableId="test.registry"
        caption="Записи"
        scrollLabel="Таблица записей"
        columns={COLUMNS}
        rows={ROWS}
        rowKey={(row) => row.id}
        empty={<p>Записей нет</p>}
        loading
        pagination={{ ...pagination, total: 500 }}
      />,
    );
    expect(screen.queryByRole("list", { name: "Страницы" })).toBeNull();
  });
});
