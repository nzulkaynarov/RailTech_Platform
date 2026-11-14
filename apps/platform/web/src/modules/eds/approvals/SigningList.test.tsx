import { fireEvent, screen, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import { server } from "../../../test/server";
import { renderUi } from "../../../test/renderUi";
import { SigningList } from "./SigningList";

const ROW = {
  id: "40000000-0000-4000-8000-000000000116",
  kind: "contract",
  number: "Д-501",
  title: "Договор Д-501",
  amount: null,
  currency: null,
  created_at: "2026-11-14T08:00:00Z",
};

describe("«Визы и подписи» (ADR-0025, план 0.8)", () => {
  it("виза: «Согласовать» и «Вернуть с замечанием» с замечанием, а не «Подписать»", async () => {
    let sent: unknown = null;
    server.use(
      http.get("*/api/v1/eds/signing-approvals", () =>
        HttpResponse.json({ items: [{ ...ROW, action: "visa", step: "Виза бухгалтера" }] }),
      ),
      http.post("*/api/v1/eds/signing-approvals/:id/decision", async ({ request }) => {
        sent = await request.json();
        return new HttpResponse(null, { status: 204 });
      }),
    );
    renderUi(<SigningList />);
    const list = await screen.findByRole("list", { name: "Визы и подписи" });
    expect(within(list).getByText("Виза бухгалтера")).toBeVisible();
    expect(within(list).queryByRole("button", { name: "Подписать" })).toBeNull();
    fireEvent.click(within(list).getByRole("button", { name: "Вернуть с замечанием" }));
    const dialog = await screen.findByRole("dialog", { name: "Замечание" });
    fireEvent.change(within(dialog).getByLabelText("Причина, её увидит автор"), {
      target: { value: "Нет графика платежей" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Вернуть с замечанием" }));
    await screen.findByText("Решение сохранено");
    expect(sent).toEqual({ decision: "return", comment: "Нет графика платежей" });
  });

  it("подпись: «Подписать» и «Отказать»", async () => {
    server.use(
      http.get("*/api/v1/eds/signing-approvals", () =>
        HttpResponse.json({ items: [{ ...ROW, action: "sign", step: "Подписать" }] }),
      ),
    );
    renderUi(<SigningList />);
    const list = await screen.findByRole("list", { name: "Визы и подписи" });
    expect(within(list).getByRole("button", { name: "Подписать" })).toBeVisible();
    expect(within(list).getByRole("button", { name: "Отказать" })).toBeVisible();
  });
});
