import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

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
});
