import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderAt, setupApprovalTests, signIn } from "../../../test/approvalsKit";
import { confirmDialog } from "../../../test/confirmDialog";

// D17G-2 (гейт D1-7): после одобрения в карточке КП — отчёт «Отправка клиенту» по каналам с причиной; тот, кто отправляет
// КП (раздел «Клиенты» полный), может отправить по невыбранному каналу и повторно — по не сработавшему.
setupApprovalTests(1440);

const APPROVED = `/eds/drafts/${encodeURIComponent("КП-2026/113")}`;

describe("Отправка клиенту: отчёт по каналам", () => {
  it("менеджер видит, что ушло и что нет, и отправляет почту повторно", async () => {
    signIn("manager@demo.example");
    renderAt(APPROVED);

    const report = await screen.findByRole("list", { name: "Каналы отправки" });
    expect(within(report).getByText("Telegram-бот — не выбрано при одобрении")).toBeVisible();
    expect(within(report).getByText("Кабинет — опубликовано")).toBeVisible();
    expect(within(report).getByText("Почта — не отправлено: письмо не ушло")).toBeVisible();

    fireEvent.click(within(report).getByRole("button", { name: "Отправить повторно: Почта" }));

    expect(
      await within(report).findByText("Почта — передано почтовому сервису, итог ещё не пришёл"),
    ).toBeVisible();
    expect(within(report).queryByRole("button", { name: /Почта/ })).toBeNull();
    expect(within(report).getByRole("button", { name: "Отправить: Telegram-бот" })).toBeVisible();
  });

  it("директор (раздел «Клиенты» полный, C1-G-4) тоже может отправить", async () => {
    signIn("director@demo.example");
    renderAt(APPROVED);
    const report = await screen.findByRole("list", { name: "Каналы отправки" });
    expect(within(report).getByText("Почта — не отправлено: письмо не ушло")).toBeVisible();
    expect(within(report).getAllByRole("button")).toHaveLength(2);
  });

  it("одобрение без почты у клиента: почта выключена с причиной, после одобрения — «не выбрано» без кнопки", async () => {
    signIn("director@demo.example");
    renderAt(`/eds/drafts/${encodeURIComponent("КП-2026/117")}?panel=open&tab=approve`);

    const form = await screen.findByRole("form", { name: "Одобрение КП" });
    expect(within(form).getByRole("checkbox", { name: "Почта" })).toBeDisabled();
    expect(within(form).getByText("Недоступна: нет e-mail у контакта.")).toBeVisible();
    fireEvent.click(within(form).getByRole("button", { name: "Одобрить КП" }));
    await confirmDialog();

    const report = await screen.findByRole("list", { name: "Каналы отправки" });
    expect(within(report).getByText("Telegram-бот — отправлено")).toBeVisible();
    expect(within(report).getByText("Кабинет — опубликовано")).toBeVisible();
    expect(within(report).getByText("Почта — не выбрано при одобрении")).toBeVisible();
    expect(within(report).queryByRole("button")).toBeNull();
  });
});
