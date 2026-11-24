import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import { readDocLinks } from "../../../mocks/fixtures/projects";
import { confirmDialog } from "../../../test/confirmDialog";
import { renderAt, setupProjectTests, signIn } from "../../../test/projectsKit";
import { server } from "../../../test/server";

// ДК-3б: «Ссылка клиента в Кабинете» в карточке проекта — у договора, счёта и акта; отзыв — у того, кто их отправляет.
setupProjectTests();

const PR97 = `/eds/projects/${encodeURIComponent("ПР-2026-097")}`;

async function open(user: string) {
  signIn(user);
  renderAt(PR97);
  await screen.findByRole("region", { name: "Документы проекта" });
}

/** Блоки «Ссылка клиента в Кабинете» — по одному на договор, счёт и акт (порядок строк документов). */
async function blocks(count = 3): Promise<[HTMLElement, HTMLElement, HTMLElement]> {
  await waitFor(() => {
    expect(screen.getAllByRole("heading", { name: "Ссылка клиента в Кабинете" })).toHaveLength(
      count,
    );
  });
  const cards = screen
    .getAllByRole("heading", { name: "Ссылка клиента в Кабинете" })
    .map((h) => h.closest<HTMLElement>(".ant-card"));
  const [contract, invoice, act] = cards;
  if (!contract || !invoice || !act) throw new Error("нет блока ссылки у договора, счёта или акта");
  return [contract, invoice, act];
}

describe("Ссылка клиента на договор, счёт и акт", () => {
  it("бухгалтер видит у каждого документа получателей без полного адреса и открытие", async () => {
    await open("accountant@demo.example");
    const [contract, invoice, act] = await blocks();
    // договор: два получателя, один открывал, второй нет
    expect(within(contract).getByText("Получатель — d***@demo-signal.example.")).toBeVisible();
    expect(within(contract).getByText("Получатель — b***@demo-signal.example.")).toBeVisible();
    expect(within(contract).getByText(/Клиент открывал: /)).toBeVisible();
    expect(within(contract).getByText("Клиент ещё не открывал.")).toBeVisible();
    expect(within(invoice).getByText("Клиент ещё не открывал.")).toBeVisible();
    expect(within(act).getByText(/Клиент открывал: /)).toBeVisible();
    expect(document.body.textContent).not.toMatch(/[a-z]{2,}@demo-signal/);
  });

  it("отзыв гасит ссылки только этого документа, после одного подтверждения", async () => {
    await open("accountant@demo.example");
    const [contract, invoice, act] = await blocks();

    fireEvent.click(within(invoice).getByRole("button", { name: "Отозвать ссылку" }));
    expect(
      await screen.findByRole("dialog", { name: "Отозвать ссылку на счёт?" }),
    ).toBeInTheDocument();
    await confirmDialog();

    expect(
      await within(invoice).findByText(/Ссылка отозвана: клиент по ней ничего не откроет/),
    ).toBeVisible();
    expect(within(invoice).queryByRole("button", { name: "Отозвать ссылку" })).toBeNull();
    // договор и акт — не тронуты
    expect(within(contract).getByRole("button", { name: "Отозвать ссылку" })).toBeVisible();
    expect(within(act).getByRole("button", { name: "Отозвать ссылку" })).toBeVisible();
    expect(readDocLinks("invoice", 4401).map((l) => l.state)).toEqual(["revoked"]);
    expect(readDocLinks("contract", 301).map((l) => l.state)).toEqual(["active", "active"]);
  });

  it("отказ в подтверждении ничего не отзывает", async () => {
    await open("accountant@demo.example");
    const [contract] = await blocks();
    fireEvent.click(within(contract).getByRole("button", { name: "Отозвать ссылку" }));
    fireEvent.click(await screen.findByRole("button", { name: "Отмена" }));
    await new Promise((resolve) => setTimeout(resolve, 300));
    expect(readDocLinks("contract", 301).map((l) => l.state)).toEqual(["active", "active"]);
  });

  it("сотрудник без права отправлять документы блока не видит", async () => {
    await open("manager@demo.example");
    await waitFor(() => {
      expect(screen.getByText("ДОГ-2026/097")).toBeVisible();
    });
    await new Promise((resolve) => setTimeout(resolve, 300));
    expect(screen.queryByRole("heading", { name: "Ссылка клиента в Кабинете" })).toBeNull();
  });

  it("истёкшая и отозванная ссылки — короткая строка состояния без кнопки", async () => {
    server.use(
      http.get("*/eds/projects/:ref/documents/contract/:docId/client-links", () =>
        HttpResponse.json({
          links: [
            {
              recipient_hint: "d***@demo-signal.example",
              sent_at: "2026-09-01T10:00:00+05:00",
              first_opened_at: null,
              last_opened_at: null,
              expires_at: "2026-10-01T10:00:00+05:00",
              state: "expired",
            },
          ],
          can_revoke: false,
        }),
      ),
    );
    await open("accountant@demo.example");
    const [contract] = await blocks();
    expect(within(contract).getByText("Срок ссылки вышел.")).toBeVisible();
    expect(within(contract).queryByRole("button")).toBeNull();
  });
});
