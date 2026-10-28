import { cleanup, fireEvent, screen, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import type { MemoApprovalCard } from "../../../shared/api/generated/model";
import { server } from "../../../test/server";
import { panelEl, renderAt, setupApprovalTests, signIn } from "../../../test/approvalsKit";
import { nextStepLabel } from "./model";

setupApprovalTests();

const MEMO = (number: string) => `/eds/approvals/${encodeURIComponent(number)}`;

async function openForm(number = "СЗ-2026/014", user = "director@demo.example") {
  signIn(user);
  const view = renderAt(MEMO(number));
  const panel = await panelEl();
  const form = await within(panel).findByRole("form", { name: "Согласование документа" });
  return { ...view, panel, form };
}

describe("Согласование: форма", () => {
  it("служебка с суммой: после директора документ получит бухгалтер; «Согласовать» активна", async () => {
    const { form } = await openForm();

    expect(within(form).getByRole("button", { name: "Согласовать" })).toBeEnabled();
    expect(within(form).getByRole("group", { name: "Что произойдёт" })).toHaveTextContent(
      "Дальше документ получит: Бухгалтер.",
    );
  });

  it("заявление без суммы: шага бухгалтера нет", async () => {
    const { form } = await openForm("ЗЯ-2026/003");

    expect(within(form).getByRole("group", { name: "Что произойдёт" })).toHaveTextContent(
      "Автор получит уведомление с вашим комментарием.",
    );
    expect(within(form).queryByText(/Дальше документ получит/)).toBeNull();
  });

  it("«Вернуть» и «Отклонить» неактивны с подписью, пока нет комментария", async () => {
    const { form } = await openForm();
    const back = within(form).getByRole("button", { name: "Вернуть на доработку" });
    const reject = within(form).getByRole("button", { name: "Отклонить" });

    expect(back).toBeDisabled();
    expect(reject).toBeDisabled();
    expect(back).toHaveAccessibleDescription(/кнопки неактивны, пока он пуст/);

    fireEvent.change(within(form).getByLabelText("Комментарий"), { target: { value: "  " } });
    expect(reject).toBeDisabled();
    fireEvent.change(within(form).getByLabelText("Комментарий"), {
      target: { value: "Нет счёта" },
    });
    expect(back).toBeEnabled();
    expect(reject).toBeEnabled();
  });

  it("сбой решения: «Не сохранено: …», комментарий остаётся и сохранён в черновике", async () => {
    server.use(
      http.post("*/eds/memo-approvals/:id/decision", () =>
        HttpResponse.json(
          { code: "BACKEND_UNAVAILABLE", message: "Сервис недоступен.", source: "eds" },
          { status: 503 },
        ),
      ),
    );
    const { form } = await openForm();
    fireEvent.change(within(form).getByLabelText("Комментарий"), {
      target: { value: "Нет счёта" },
    });

    fireEvent.click(within(form).getByRole("button", { name: "Отклонить" }));

    expect(
      await within(form).findByText(
        "Не сохранено: сервис документов не отвечает, комментарий остался в форме",
      ),
    ).toBeVisible();
    expect(within(form).getByLabelText("Комментарий")).toHaveValue("Нет счёта");
    expect(
      Object.keys(window.sessionStorage).filter((k) => k.startsWith("rt-pf-memo-draft-v1")),
    ).toHaveLength(1);
  });

  it("409: документ уже решён другим — сообщение словами, карточка обновилась", async () => {
    const { panel } = await openForm();
    await fetch("/api/v1/eds/memo-approvals/50000000-0000-4000-8000-000000000014/decision", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ decision: "reject", comment: "дубль" }),
    });
    const form = within(panel).getByRole("form", { name: "Согласование документа" });

    fireEvent.click(within(form).getByRole("button", { name: "Согласовать" }));

    expect(
      (
        await screen.findAllByText(
          "Не сохранено: документ уже решён другим согласующим, карточка обновлена",
        )
      ).length,
    ).toBeGreaterThan(0);
    expect(await within(panel).findByRole("heading", { name: "Документ отклонён" })).toBeVisible();
  });

  it("автор без права решения: карточка в режиме чтения, формы нет", async () => {
    signIn("manager@demo.example");
    renderAt(MEMO("СЗ-2026/014"));
    const panel = await panelEl();

    expect(
      await within(panel).findByRole("heading", { name: "Документ на согласовании" }),
    ).toBeVisible();
    expect(within(panel).queryByRole("form")).toBeNull();
    expect(await screen.findByText("Только просмотр")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Согласовать" })).toBeNull();
  });
});

describe("Согласование: шаг бухгалтера", () => {
  it("бухгалтер на своём шаге: «Принять к оплате» и «Вернуть», без текстов директора", async () => {
    const { form } = await openForm("СЗ-2026/015", "accountant@demo.example");

    expect(within(form).getByRole("button", { name: "Принять к оплате" })).toBeEnabled();
    expect(within(form).getByRole("button", { name: "Вернуть" })).toBeDisabled();
    expect(within(form).queryByRole("button", { name: "Согласовать" })).toBeNull();
    expect(within(form).getByRole("group", { name: "Что произойдёт" })).toHaveTextContent(
      "появится в «Счета и оплаты»",
    );
  });

  it("«Принять к оплате» решает шаг и закрывает маршрут", async () => {
    const { form, panel } = await openForm("СЗ-2026/015", "accountant@demo.example");

    fireEvent.click(within(form).getByRole("button", { name: "Принять к оплате" }));

    expect((await screen.findAllByText("Документ принят к оплате")).length).toBeGreaterThan(0);
    expect(
      await within(panel).findByRole("heading", { name: "Документ согласован" }),
    ).toBeVisible();
  });

  it("бухгалтер до своей очереди: формы нет, шаг у директора", async () => {
    signIn("accountant@demo.example");
    renderAt(MEMO("СЗ-2026/014"));
    const panel = await panelEl();

    expect(
      await within(panel).findByRole("heading", { name: "Документ на согласовании" }),
    ).toBeVisible();
    expect(within(panel).queryByRole("form")).toBeNull();
  });

  it("шаг бухгалтера решает держатель `eds.payments` full: у бухгалтера «Принять к оплате», у директора (только чтение счетов, D2-4) формы нет", async () => {
    const { form } = await openForm("СЗ-2026/015", "accountant@demo.example");
    expect(within(form).getByRole("button", { name: "Принять к оплате" })).toBeEnabled();
    cleanup();

    signIn("director@demo.example");
    renderAt(MEMO("СЗ-2026/015"));
    const panel = await panelEl();
    expect((await screen.findAllByText(/СЗ-2026\/015/)).length).toBeGreaterThan(0);
    expect(within(panel).queryByRole("form", { name: "Согласование документа" })).toBeNull();
  });
});

describe("шаги маршрута", () => {
  const step = (label: string, status: MemoApprovalCard["steps"][number]["status"]) => ({
    label,
    status,
    decided_by: null,
    decided_at: null,
    comment: null,
  });

  it("следующий шаг после текущего; шага нет — null", () => {
    expect(nextStepLabel([step("Директор", "current"), step("Бухгалтер", "pending")])).toBe(
      "Бухгалтер",
    );
    expect(nextStepLabel([step("Директор", "current")])).toBeNull();
    expect(nextStepLabel([step("Директор", "approved")])).toBeNull();
  });
});
