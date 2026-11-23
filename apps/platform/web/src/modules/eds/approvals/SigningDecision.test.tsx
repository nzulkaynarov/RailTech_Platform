import { fireEvent, screen, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { describe, expect, it, vi } from "vitest";

import { server } from "../../../test/server";
import { renderUi } from "../../../test/renderUi";
import { SigningDecision } from "./SigningDecision";

const ID = "40000000-0000-4000-8000-000000000116";
const ROW = {
  id: ID,
  kind: "contract",
  number: "Д-501",
  title: "Договор Д-501",
  amount: null,
  currency: null,
  created_at: "2026-11-14T08:00:00Z",
};

function listWith(extra: object) {
  server.use(
    http.get("*/api/v1/eds/signing-approvals", () =>
      HttpResponse.json({ items: [{ ...ROW, ...extra }] }),
    ),
  );
}

describe("Решение по подписи и визе из строки очереди (ADR-0025, ГЛ-1)", () => {
  it("виза: «Согласовать» и «Вернуть с замечанием» с замечанием, а не «Подписать»", async () => {
    let sent: unknown = null;
    listWith({ action: "visa", step: "Виза бухгалтера" });
    server.use(
      http.post("*/api/v1/eds/signing-approvals/:id/decision", async ({ request }) => {
        sent = await request.json();
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const onClose = vi.fn();
    renderUi(<SigningDecision id={ID} onClose={onClose} />);
    const window = await screen.findByRole("dialog", { name: "Договор Д-501" });
    expect(within(window).getByText("Виза бухгалтера")).toBeInTheDocument();
    expect(within(window).queryByRole("button", { name: "Подписать" })).toBeNull();
    fireEvent.click(within(window).getByRole("button", { name: "Вернуть с замечанием" }));
    const reasonWindow = await screen.findByRole("dialog", { name: "Замечание" });
    fireEvent.change(within(reasonWindow).getByLabelText("Причина, её увидит автор"), {
      target: { value: "Нет графика платежей" },
    });
    fireEvent.click(within(reasonWindow).getByRole("button", { name: "Вернуть с замечанием" }));
    await screen.findByText("Решение сохранено");
    expect(sent).toEqual({ decision: "return", comment: "Нет графика платежей" });
    expect(onClose).toHaveBeenCalled();
  });

  it("подпись: «Подписать» и «Отказать»; сумма — с разрядами и словом валюты", async () => {
    listWith({
      kind: "act",
      title: "Акт АКТ-2026/001",
      amount: "604800000.00",
      currency: "UZS",
      action: "sign",
      step: "Подписать",
    });
    renderUi(<SigningDecision id={ID} onClose={() => undefined} />);
    const window = await screen.findByRole("dialog", { name: "Акт АКТ-2026/001" });
    expect(within(window).getByRole("button", { name: "Подписать" })).toBeInTheDocument();
    expect(within(window).getByRole("button", { name: "Отказать" })).toBeInTheDocument();
    expect(within(window).queryByText(/604800000\.00/)).toBeNull();
    expect(within(window).getByText(/604\s800\s000\sсум/)).toBeInTheDocument();
  });

  it("шаг уже решён без вас — окно закрывается само, лишнего не показывает", async () => {
    server.use(http.get("*/api/v1/eds/signing-approvals", () => HttpResponse.json({ items: [] })));
    const onClose = vi.fn();
    renderUi(<SigningDecision id={ID} onClose={onClose} />);
    await vi.waitFor(() => {
      expect(onClose).toHaveBeenCalled();
    });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("без адреса `?signing=` ничего не показывает и список не запрашивает", () => {
    const asked = vi.fn();
    server.use(
      http.get("*/api/v1/eds/signing-approvals", () => {
        asked();
        return HttpResponse.json({ items: [] });
      }),
    );
    renderUi(<SigningDecision id={null} onClose={() => undefined} />);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(asked).not.toHaveBeenCalled();
  });
});
