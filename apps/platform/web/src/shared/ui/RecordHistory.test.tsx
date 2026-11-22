import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderUi } from "../../test/renderUi";
import { RecordHistory, type RecordHistoryEntry } from "./RecordHistory";

const entries: RecordHistoryEntry[] = [
  {
    at: "2026-11-20T10:00:00Z",
    by: "Рустамов А.К.",
    action: "Договор подписан",
    filter: "contract",
  },
  {
    at: "2026-11-19T10:00:00Z",
    by: null,
    action: "Акт выпущен",
    filter: "act",
    comment: "Без замечаний",
  },
  {
    at: "2026-11-18T10:00:00Z",
    by: "Каримова Н.",
    action: "КП принято",
    filter: "quote",
    onBehalf: { channel: "email", person: "Юсупов Н." },
  },
  { at: "2026-11-17T10:00:00Z", by: "Система", action: "Проект открыт", filter: null },
];
const filters = [
  { key: "quote", label: "КП" },
  { key: "contract", label: "Договор" },
  { key: "invoice", label: "Счёт" },
  { key: "act", label: "Акт" },
];

describe("RecordHistory", () => {
  it("запись — действие, кто, комментарий, «отмечено сотрудником»; системная запись подписана «Система»", () => {
    renderUi(<RecordHistory label="История" entries={entries} />);
    const rows = within(screen.getByRole("list", { name: "История" })).getAllByRole("listitem");
    expect(rows).toHaveLength(4);
    expect(rows[0]).toHaveTextContent("Рустамов А.К.");
    expect(rows[1]).toHaveTextContent("Система");
    expect(rows[1]).toHaveTextContent("Без замечаний");
    expect(rows[2]).toHaveTextContent("Отмечено сотрудником");
  });

  it("фильтр: чипы только у документов с записями; выбор оставляет записи документа, «Все» возвращает список", () => {
    renderUi(<RecordHistory label="История" entries={entries} filters={filters} />);
    // у «Счёта» записей нет — чипа нет
    expect(screen.queryByRole("button", { name: "Счёт" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Акт" }));
    const rows = within(screen.getByRole("list", { name: "История" })).getAllByRole("listitem");
    expect(rows).toHaveLength(1);
    expect(rows[0]).toHaveTextContent("Акт выпущен");
    expect(screen.getByRole("button", { name: "Акт" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("button", { name: "Все" }));
    expect(
      within(screen.getByRole("list", { name: "История" })).getAllByRole("listitem"),
    ).toHaveLength(4);
  });

  it("без фильтров и с одним документом чипов нет", () => {
    renderUi(<RecordHistory label="История" entries={entries.slice(0, 1)} filters={filters} />);
    expect(screen.queryByRole("group")).toBeNull();
  });
});
