import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { readQuotes, writeQuotes } from "../../../mocks/fixtures/approvals";
import { renderAt, setupApprovalTests, signIn } from "../../../test/approvalsKit";
import { confirmDialog } from "../../../test/confirmDialog";

// ДК-1: ссылка клиента на КП в Кабинете — состояние, кому ушла, открывал ли; «Отозвать ссылку» — у того, кто отправляет КП.
setupApprovalTests(1440);

const APPROVED = `/eds/drafts/${encodeURIComponent("КП-2026/113")}`;

async function linkCard() {
  const heading = await screen.findByRole("heading", { name: "Ссылка клиента в Кабинете" });
  const card = heading.closest(".ant-card");
  if (!(card instanceof HTMLElement)) throw new Error("нет карточки ссылки клиента");
  return card;
}

describe("Ссылка клиента на КП", () => {
  it("менеджер видит срок, получателя и открытие, отзывает ссылку после подтверждения", async () => {
    signIn("manager@demo.example");
    renderAt(APPROVED);

    const card = await linkCard();
    expect(within(card).getByText("Ссылка действует до 27.12.2026.")).toBeVisible();
    expect(within(card).getByText("Получатель — a***@demo-put.example.")).toBeVisible();
    expect(within(card).getByText(/Клиент открывал: /)).toBeVisible();

    fireEvent.click(within(card).getByRole("button", { name: "Отозвать ссылку" }));
    expect(
      await screen.findByRole("dialog", { name: "Отозвать ссылку на КП?" }),
    ).toBeInTheDocument();
    await confirmDialog();

    expect(
      await within(card).findByText(/Ссылка отозвана: клиент по ней ничего не откроет/),
    ).toBeVisible();
    expect(within(card).queryByRole("button", { name: "Отозвать ссылку" })).toBeNull();
  });

  it("отказ в подтверждении ничего не отзывает", async () => {
    signIn("manager@demo.example");
    renderAt(APPROVED);
    const card = await linkCard();

    fireEvent.click(within(card).getByRole("button", { name: "Отозвать ссылку" }));
    fireEvent.click(await screen.findByRole("button", { name: "Отмена" }));

    await new Promise((resolve) => setTimeout(resolve, 300));
    expect(readQuotes().find((q) => q.number === "КП-2026/113")?.client_link?.state).toBe("active");
    expect(within(card).getByText("Ссылка действует до 27.12.2026.")).toBeVisible();
  });

  it("отозванная ссылка не предлагает отзыв ещё раз", async () => {
    writeQuotes(
      readQuotes().map((q) =>
        q.number === "КП-2026/113" && q.client_link
          ? { ...q, client_link: { ...q.client_link, state: "revoked", can_revoke: false } }
          : q,
      ),
    );
    signIn("director@demo.example");
    renderAt(APPROVED);

    const card = await linkCard();

    expect(within(card).getByText(/Ссылка отозвана/)).toBeVisible();
    expect(within(card).queryByRole("button")).toBeNull();
  });

  it("у КП, которое клиенту ещё не уходило, карточки ссылки нет", async () => {
    signIn("director@demo.example");
    renderAt(`/eds/drafts/${encodeURIComponent("КП-2026/117")}`);

    await screen.findByRole("heading", { name: /КП-2026\/117/ });
    expect(screen.queryByRole("heading", { name: "Ссылка клиента в Кабинете" })).toBeNull();
  });
});
