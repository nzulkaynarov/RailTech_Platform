import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { usePanelsStore } from "../../../../app/shell/panelsStore";
import { resetContractTemplates } from "../../../../mocks/contractTemplates";
import { resetCompanyMock } from "../../../../mocks/fixtures/company";
import { endSession } from "../../../../mocks/mockSession";
import i18n from "../../../../shared/i18n";
import { renderApp, signInAs } from "../../../../test/renderApp";
import { setViewportWidth } from "../../../../test/viewport";

beforeEach(() => {
  window.localStorage.clear();
  resetCompanyMock();
  resetContractTemplates();
  usePanelsStore.setState({ entries: {} });
  setViewportWidth(1440);
  void i18n.changeLanguage("ru");
});
afterEach(() => {
  endSession();
});

async function rowOf(name: string): Promise<HTMLElement> {
  const table = await screen.findByRole("table", { name: "Шаблоны договоров" });
  return within(table).getByRole("row", { name: new RegExp(name) });
}

function openMenu(row: HTMLElement, name: string): void {
  fireEvent.click(within(row).getByRole("button", { name: new RegExp(`Действия.*${name}`) }));
}

describe("Документы · Шаблоны · Договоры (ДОК-10)", () => {
  it("список: статус, редакция, кто утвердил, и пометка, что неутверждённый в проекте не предлагается", async () => {
    signInAs("admin@demo.example");
    renderApp("/admin/templates?tab=contracts");
    const approved = await rowOf("Договор с клиентом · поставка");
    expect(within(approved).getByText("Утверждён")).toBeInTheDocument();
    expect(approved).toHaveTextContent("ред. 3");
    expect(approved).toHaveTextContent("утвердил А. Юсупов");
    expect(await rowOf("Договор с клиентом · услуги")).toHaveTextContent("На утверждении");
    const draft = await rowOf("Договор с партнёром · услуги");
    expect(draft).toHaveTextContent("Черновик");
    expect(draft).toHaveTextContent("в проекте не предлагается");
  });

  it("«Утвердить» — у держателя «Право» (администратор): шаблон становится утверждённым", async () => {
    signInAs("admin@demo.example");
    renderApp("/admin/templates?tab=contracts");
    const row = await rowOf("Договор с клиентом · услуги");
    openMenu(row, "Договор с клиентом · услуги");
    fireEvent.click(await screen.findByRole("menuitem", { name: "Утвердить" }));
    await waitFor(async () => {
      expect(
        within(await rowOf("Договор с клиентом · услуги")).getByText("Утверждён"),
      ).toBeInTheDocument();
    });
  });

  it("директор без зоны «Право» не видит «Утвердить»", async () => {
    signInAs("director@demo.example");
    renderApp("/admin/templates?tab=contracts");
    const row = await rowOf("Договор с клиентом · услуги");
    expect(within(row).queryByRole("button", { name: /Действия/ })).toBeNull();
  });

  it("«Новая редакция» делает черновик; «На утверждение» отправляет его юристу", async () => {
    signInAs("admin@demo.example");
    renderApp("/admin/templates?tab=contracts");
    const row = await rowOf("Договор с клиентом · поставка");
    openMenu(row, "Договор с клиентом · поставка");
    fireEvent.click(await screen.findByRole("menuitem", { name: "Новая редакция" }));
    const table = await screen.findByRole("table", { name: "Шаблоны договоров" });
    await waitFor(() => {
      expect(within(table).getByText("ред. 4")).toBeInTheDocument();
    });
    const draft = within(table).getByText("ред. 4").closest("tr");
    expect(draft).not.toBeNull();
    expect(draft).toHaveTextContent("Черновик");
    openMenu(draft as HTMLElement, "Договор с клиентом · поставка");
    fireEvent.click(await screen.findByRole("menuitem", { name: "На утверждение" }));
    await waitFor(() => {
      expect(within(table).getAllByText("На утверждении").length).toBe(2);
    });
  });

  it("юрист без раздела Настроек утверждает на странице «Документы · Шаблоны · Договоры»", async () => {
    signInAs("lawyer@demo.example");
    renderApp("/eds/contract-templates");
    const row = await rowOf("Договор с клиентом · услуги");
    openMenu(row, "Договор с клиентом · услуги");
    fireEvent.click(await screen.findByRole("menuitem", { name: "Утвердить" }));
    await waitFor(async () => {
      expect(
        within(await rowOf("Договор с клиентом · услуги")).getByText("Утверждён"),
      ).toBeInTheDocument();
    });
  });
});
