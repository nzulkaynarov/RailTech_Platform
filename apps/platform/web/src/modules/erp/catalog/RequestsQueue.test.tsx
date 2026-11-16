import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { readErpCatalog } from "../../../mocks/fixtures/erpCatalog";
import { findModal, renderAt, setupCatalogTests, signIn } from "../../../test/catalogKit";

setupCatalogTests();

/** ADR-0027: «Новые из заявок» — черновики из строк расчёта, спрос, заявки, подсказка дубля и слияние. */
async function openRequests(email = "supply@demo.example") {
  signIn(email);
  renderAt("/erp/catalog?review=requests");
  return screen.findByRole("table", { name: "Новые позиции из заявок" });
}

describe("Новые из заявок", () => {
  it("самые спрашиваемые сверху: спрос, номера заявок и похожая карточка", async () => {
    const table = await openRequests();
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(2);
    const first = rows[0] as HTMLElement;
    expect(within(first).getByText("реле защиты рз-1")).toBeVisible();
    expect(within(first).getByText("3")).toBeVisible();
    expect(within(first).getByText("ЗВ-2026-014")).toBeVisible();
    expect(within(first).getByText("и ещё 1")).toBeVisible();
    expect(
      within(first).getByText(/Похожа на «Реле защиты РЗ-1» RT-0002 — название совпало/),
    ).toBeVisible();
    expect(within(rows[1] as HTMLElement).queryByRole("button", { name: /^Слить/ })).toBeNull();
    expect(await screen.findByText("Новые из заявок · 2")).toBeVisible();
  });

  it("«Слить» после подтверждения переносит позицию в похожую карточку", async () => {
    const table = await openRequests();
    fireEvent.click(
      within(table).getByRole("button", { name: "Слить с RT-0002: «реле защиты рз-1»" }),
    );
    const modal = await findModal("Слить «реле защиты рз-1»?");
    fireEvent.click(within(modal).getByRole("button", { name: "Слить" }));
    expect(await screen.findByText("Карточки слиты")).toBeVisible();
    await waitFor(() => {
      expect(within(table).queryByText("реле защиты рз-1")).toBeNull();
    });
    expect(readErpCatalog().items.some((i) => i.id === "20")).toBe(false);
  });
});
