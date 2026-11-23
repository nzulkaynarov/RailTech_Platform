import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import "../../i18n";
import { DataTable, type DataColumn } from "./DataTable";
import { TABLES_STORAGE_KEY, sanitizeSettings, useTablesStore } from "./tableSettings";

interface Doc {
  id: string;
  number: string;
  subject: string;
  amount: string;
}

const ROWS: Doc[] = [
  { id: "1", number: "СЗ-001", subject: "Закупка мебели", amount: "3 600 000" },
  { id: "2", number: "СЗ-002", subject: "Командировка", amount: "750 000" },
];

const COLUMNS: DataColumn<Doc>[] = [
  { id: "number", header: "Номер", width: 120, cell: (row) => row.number },
  { id: "subject", header: "Тема", width: null, cell: (row) => row.subject },
  { id: "amount", header: "Сумма", width: 136, numeric: true, cell: (row) => row.amount },
];

function renderTable() {
  return render(
    <DataTable
      tableId="test.docs"
      caption="Документы"
      scrollLabel="Таблица документов"
      columns={COLUMNS}
      rows={ROWS}
      rowKey={(row) => row.id}
    />,
  );
}

function headers(): string[] {
  return screen.getAllByRole("columnheader").map((th) => th.textContent);
}

function widths(): string[] {
  const table = screen.getByRole("table");
  return [...table.querySelectorAll("colgroup > col")].map(
    (col) => (col as HTMLElement).style.width,
  );
}

function openMenu() {
  fireEvent.click(screen.getByRole("button", { name: "Столбцы" }));
  return screen.getByRole("group", { name: "Столбцы" });
}

beforeEach(() => {
  window.localStorage.clear();
  useTablesStore.setState({ entries: {} });
});

describe("DataTable", () => {
  it("renders a row header cell and hides the column settings when the tools target is null", () => {
    render(
      <DataTable
        tableId="test.report"
        caption="Сводка"
        scrollLabel="Сводка"
        columns={[{ ...COLUMNS[0], rowHeader: true } as DataColumn<Doc>, ...COLUMNS.slice(1)]}
        rows={ROWS}
        rowKey={(row) => row.id}
        toolsTarget={null}
      />,
    );
    const rowHeaders = screen.getAllByRole("rowheader");
    expect(rowHeaders.map((th) => th.textContent)).toEqual(["СЗ-001", "СЗ-002"]);
    expect(rowHeaders[0]).toHaveAttribute("scope", "row");
    expect(screen.queryByRole("button", { name: "Столбцы" })).toBeNull();
  });

  it("по умолчанию: ширина по типу столбца, гибкий столбец без ширины, число вправо", () => {
    renderTable();
    expect(headers()).toEqual(["Номер", "Тема", "Сумма"]);
    expect(widths()).toEqual(["120px", "", "136px"]);
    expect(screen.getAllByRole("columnheader")[2]).toHaveClass("pf-col-num");
    expect(screen.getByRole("table")).toHaveStyle({ minWidth: "426px" });
  });

  it("ширина с клавиатуры: «Шире» и «Уже» в «Столбцах», сохраняется на пользователя", () => {
    renderTable();
    const menu = openMenu();
    fireEvent.click(within(menu).getByRole("button", { name: "Шире: Номер" }));
    fireEvent.click(within(menu).getByRole("button", { name: "Шире: Номер" }));
    expect(widths()[0]).toBe("152px");
    const stored = JSON.parse(window.localStorage.getItem(TABLES_STORAGE_KEY) ?? "{}") as Record<
      string,
      unknown
    >;
    expect(stored["-|test.docs"]).toEqual({ sizing: { number: 152 } });
    fireEvent.click(within(menu).getByRole("button", { name: "Уже: Номер" }));
    expect(widths()[0]).toBe("136px");
  });

  it("«Столбцы»: скрыть, переставить, закрепить; первый столбец скрыть нельзя; «Сбросить» возвращает вид", () => {
    renderTable();
    const menu = openMenu();
    expect(within(menu).getByRole("checkbox", { name: "Номер" })).toBeDisabled();

    fireEvent.click(within(menu).getByRole("checkbox", { name: "Сумма" }));
    expect(headers()).toEqual(["Номер", "Тема"]);

    fireEvent.click(within(menu).getByRole("checkbox", { name: "Сумма" }));
    fireEvent.click(within(menu).getByRole("button", { name: "Выше: Сумма" }));
    expect(headers()).toEqual(["Номер", "Сумма", "Тема"]);

    fireEvent.click(within(menu).getByRole("button", { name: "Закрепить слева: Тема" }));
    expect(headers()[0]).toBe("Тема");
    expect(within(menu).getByRole("button", { name: "Открепить: Тема" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );

    fireEvent.click(within(menu).getByRole("button", { name: "Сбросить" }));
    expect(headers()).toEqual(["Номер", "Тема", "Сумма"]);
    expect(window.localStorage.getItem(TABLES_STORAGE_KEY)).toBe("{}");
  });

  it("настройки другой вкладки с неизвестными столбцами не ломают таблицу", () => {
    useTablesStore.setState({
      entries: {
        "-|test.docs": { hidden: ["responsible", "number"], order: ["responsible", "amount"] },
      },
    });
    renderTable();
    // первый столбец не скрывается даже по сохранённой записи; неизвестные столбцы пропущены
    expect(headers()).toEqual(["Сумма", "Номер", "Тема"]);
  });
});

describe("sanitizeSettings", () => {
  it("отбрасывает мусор из хранилища", () => {
    expect(
      sanitizeSettings({
        sizing: { a: 120.4, b: -1, c: "x" },
        hidden: ["x", 1],
        order: "a",
        pinned: [],
      }),
    ).toEqual({ sizing: { a: 120 }, hidden: ["x"] });
    expect(sanitizeSettings(null)).toEqual({});
    expect(sanitizeSettings([1])).toEqual({});
  });

  it("страницы на клиенте: строк больше pageSize — переключатель под таблицей, меньше — без него", () => {
    const many: Doc[] = Array.from({ length: 5 }, (_, i) => ({
      id: String(i + 1),
      number: `СЗ-00${String(i + 1)}`,
      subject: `Тема ${String(i + 1)}`,
      amount: "1",
    }));
    const { rerender } = render(
      <DataTable
        tableId="test.pages"
        caption="Документы"
        scrollLabel="Таблица документов"
        columns={COLUMNS}
        rows={many}
        rowKey={(row) => row.id}
        pageSize={2}
      />,
    );
    expect(screen.getAllByRole("row")).toHaveLength(3);
    const pager = screen.getByRole("list", { name: "Страницы: Документы" });
    fireEvent.click(within(pager).getByTitle("3"));
    expect(screen.getByText("СЗ-005")).toBeInTheDocument();
    // после фильтра строк меньше: остаётся последняя страница, а не пустая таблица; одна страница — без переключателя
    rerender(
      <DataTable
        tableId="test.pages"
        caption="Документы"
        scrollLabel="Таблица документов"
        columns={COLUMNS}
        rows={many.slice(0, 2)}
        rowKey={(row) => row.id}
        pageSize={2}
      />,
    );
    expect(screen.getByText("СЗ-002")).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Страницы: Документы" })).toBeNull();
  });
});

describe("DataTable sorting by header (Х-15)", () => {
  const ITEMS = [
    { id: "1", number: "СЗ-10", due: "2026-03-01" as string | null },
    { id: "2", number: "СЗ-2", due: null },
    { id: "3", number: "СЗ-1", due: "2026-01-15" },
  ];
  const COLS: DataColumn<(typeof ITEMS)[number]>[] = [
    {
      id: "number",
      header: "Номер",
      width: 120,
      sortKey: "number",
      sortValue: (row) => row.number,
      cell: (row) => row.number,
    },
    {
      id: "due",
      header: "Срок",
      width: 120,
      sortKey: "due_date",
      sortValue: (row) => row.due,
      cell: (row) => row.due ?? "—",
    },
    { id: "plain", header: "Без сортировки", width: 120, cell: () => "x" },
  ];

  afterEach(cleanup);

  function Where() {
    return <output data-testid="where">{useLocation().search}</output>;
  }

  function renderSorted(url = "/", mode: "client" | "server" = "client") {
    return render(
      <MemoryRouter initialEntries={[url]}>
        <DataTable
          tableId="test.sort"
          caption="Список"
          scrollLabel="Таблица"
          columns={COLS}
          rows={ITEMS}
          rowKey={(row) => row.id}
          sortMode={mode}
        />
        <Where />
      </MemoryRouter>,
    );
  }

  const numbers = () =>
    within(screen.getByRole("table"))
      .getAllByRole("row")
      .slice(1)
      .map((tr) => (tr as HTMLTableRowElement).cells.item(0)?.textContent);
  const where = () => screen.getByTestId("where").textContent;
  const header = (name: string) => screen.getByRole("columnheader", { name: new RegExp(name) });

  it("cycles ascending, descending, off and keeps the state in the address", () => {
    renderSorted();
    expect(numbers()).toEqual(["СЗ-10", "СЗ-2", "СЗ-1"]);
    fireEvent.click(screen.getByRole("button", { name: "Номер" }));
    expect(where()).toBe("?sort=number");
    expect(numbers()).toEqual(["СЗ-1", "СЗ-2", "СЗ-10"]);
    expect(header("Номер").getAttribute("aria-sort")).toBe("ascending");
    fireEvent.click(screen.getByRole("button", { name: /Номер/ }));
    expect(where()).toBe("?sort=-number");
    expect(numbers()).toEqual(["СЗ-10", "СЗ-2", "СЗ-1"]);
    expect(header("Номер").getAttribute("aria-sort")).toBe("descending");
    fireEvent.click(screen.getByRole("button", { name: /Номер/ }));
    expect(where()).toBe("");
    expect(header("Номер").getAttribute("aria-sort")).toBe("none");
  });

  it("restores the order from the address and shows exactly one arrow", () => {
    renderSorted("/?sort=-due_date");
    expect(numbers()).toEqual(["СЗ-10", "СЗ-1", "СЗ-2"]);
    expect(document.querySelectorAll(".pf-dt-sort-arrow")).toHaveLength(1);
  });

  it("puts empty values last in both directions", () => {
    renderSorted("/?sort=due_date");
    expect(numbers()).toEqual(["СЗ-1", "СЗ-10", "СЗ-2"]);
    fireEvent.click(screen.getByRole("button", { name: /Срок/ }));
    expect(numbers()).toEqual(["СЗ-10", "СЗ-1", "СЗ-2"]);
  });

  it("ignores a field from the address that no column declares", () => {
    renderSorted("/?sort=secret");
    expect(numbers()).toEqual(["СЗ-10", "СЗ-2", "СЗ-1"]);
    expect(document.querySelectorAll(".pf-dt-sort-arrow")).toHaveLength(0);
  });

  it("makes only declared columns sortable", () => {
    renderSorted();
    expect(header("Без сортировки").getAttribute("aria-sort")).toBeNull();
    expect(screen.queryByRole("button", { name: "Без сортировки" })).toBeNull();
  });

  it("server mode keeps the rows as given and drops the page number", () => {
    renderSorted("/?sort=number&page=3", "server");
    expect(numbers()).toEqual(["СЗ-10", "СЗ-2", "СЗ-1"]);
    fireEvent.click(screen.getByRole("button", { name: /Номер/ }));
    expect(where()).toBe("?sort=-number");
  });
});
