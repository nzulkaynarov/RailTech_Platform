import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { usePanelsStore } from "../../../app/shell/panelsStore";
import { resetCompanyMock } from "../../../mocks/fixtures/company";
import { endSession } from "../../../mocks/mockSession";
import i18n from "../../../shared/i18n";
import { chooseOption } from "../../../test/fields";
import { renderApp, signInAs } from "../../../test/renderApp";
import { setViewportWidth } from "../../../test/viewport";

beforeEach(() => {
  window.localStorage.clear();
  resetCompanyMock();
  usePanelsStore.setState({ entries: {} });
  setViewportWidth(1440);
  void i18n.changeLanguage("ru");
});
afterEach(() => {
  endSession();
});

describe("«Все шаблоны» (план 2.7)", () => {
  it("шаблоны документов, писем, резолюций и ответов бота — одной таблицей; строка открывает редактор", async () => {
    signInAs("director@demo.example");
    const { router } = renderApp("/admin/templates");
    const table = await screen.findByRole("table", { name: "Шаблоны всех разделов" });
    // ДОК-13: «Условия КП» — настройки, а не шаблон; строки «КП» в таблице нет
    expect(within(table).queryByRole("link", { name: "Коммерческое предложение" })).toBeNull();
    const kinds = within(table)
      .getAllByRole("row")
      .slice(1)
      .map((row) => within(row).getAllByRole("cell")[1]?.textContent);
    expect(kinds).toContain("Резолюция");
    expect(kinds).toContain("Письмо клиенту");

    await chooseOption(screen.getByRole("combobox", { name: "Вид шаблона" }), "Договор");
    await waitFor(() => {
      expect(
        within(table)
          .getAllByRole("row")
          .slice(1)
          .every((row) => within(row).getAllByRole("cell")[1]?.textContent === "Договор"),
      ).toBe(true);
    });

    fireEvent.click(within(table).getByRole("link", { name: "Договор поставки (наш)" }));
    expect(
      await screen.findByRole("region", { name: "Изменить шаблон документа" }),
    ).toBeInTheDocument();
    await waitFor(() => {
      expect(new URLSearchParams(router.state.location.search).get("template")).toBeNull();
    });
    expect(new URLSearchParams(router.state.location.search).get("tab")).toBe("documents");
  });
});
