import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderAt, setupCalcTests, signIn } from "../../../test/calcKit";

setupCalcTests();

async function openCalc(email: string, number: string) {
  signIn(email);
  renderAt(`/erp/calc/${encodeURIComponent(number)}`);
  expect(
    await screen.findByRole("heading", { level: 1, name: `Расчёт по заявке ${number}` }),
  ).toBeVisible();
}

describe("Расчёт · «Закрыть заявку» (ЛХ-2)", () => {
  it("до отправки КП доступны все причины; «Другое» требует комментарий; заявка закрывается", async () => {
    await openCalc("universal@demo.example", "ЗВ-2026-101");
    fireEvent.click(screen.getByRole("button", { name: "Закрыть заявку" }));
    const dialog = await screen.findByRole("dialog", { name: "Закрыть заявку ЗВ-2026-101" });
    const submit = within(dialog).getByRole("button", { name: "Закрыть заявку" });
    expect(await within(dialog).findByRole("radio", { name: "Тест" })).toBeEnabled();
    expect(submit).toBeDisabled();
    fireEvent.click(within(dialog).getByRole("radio", { name: "Другое — комментарий" }));
    expect(submit).toBeDisabled();
    fireEvent.change(within(dialog).getByRole("textbox", { name: "Комментарий" }), {
      target: { value: "Передали другому" },
    });
    expect(submit).toBeEnabled();
    fireEvent.click(submit);
    await waitFor(() => {
      expect(screen.getByText("Заявка закрыта: Другое — комментарий")).toBeVisible();
    });
    expect(screen.queryByRole("button", { name: "Закрыть заявку" })).toBeNull();
    // закрытая заявка не показывает «КП у директора на одобрении» и статус расчёта
    expect(screen.queryByText(/у директора на одобрении/i)).toBeNull();
    expect(screen.queryByText(/Черновик КП у директора/)).toBeNull();
  });

  it("после отправки КП причины «Ошибка», «Дубль», «Тест» недоступны", async () => {
    await openCalc("universal@demo.example", "ЗВ-2026-109");
    fireEvent.click(screen.getAllByRole("button", { name: "Закрыть заявку" })[0] as HTMLElement);
    const dialog = await screen.findByRole("dialog", { name: "Закрыть заявку ЗВ-2026-109" });
    expect(await within(dialog).findByRole("radio", { name: "Дубль" })).toBeDisabled();
    expect(within(dialog).getByRole("radio", { name: "Клиент передумал" })).toBeEnabled();
  });

  it("без права на расчёт кнопки нет", async () => {
    await openCalc("accountant@demo.example", "ЗВ-2026-101");
    expect(screen.queryByRole("button", { name: "Закрыть заявку" })).toBeNull();
  });

  it("черновик без задания расчёта: карточка заявки и «Закрыть заявку»", async () => {
    signIn("universal@demo.example");
    renderAt(`/erp/calc/${encodeURIComponent("ЗВ-2026-120")}`);
    expect(await screen.findByText(/Клиент просит цену на 40 т щебня/)).toBeVisible();
    expect(screen.getByText(/Расчёта по заявке пока нет/)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Закрыть заявку" }));
    const dialog = await screen.findByRole("dialog", { name: "Закрыть заявку ЗВ-2026-120" });
    fireEvent.click(await within(dialog).findByRole("radio", { name: "Тест" }));
    fireEvent.click(within(dialog).getByRole("button", { name: "Закрыть заявку" }));
    await waitFor(() => {
      expect(screen.getByText("Заявка закрыта: Тест")).toBeVisible();
    });
    expect(screen.queryByRole("button", { name: "Закрыть заявку" })).toBeNull();
  });
});
