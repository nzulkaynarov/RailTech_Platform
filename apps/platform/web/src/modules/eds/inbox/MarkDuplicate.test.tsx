import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderAt, setupLetterTests, signIn } from "../../../test/lettersKit";

setupLetterTests();

async function openCard(email: string, number: string) {
  signIn(email);
  renderAt(`/eds/inbox/${number}`);
  expect(await screen.findByRole("heading", { level: 1, name: `Письмо ${number}` })).toBeVisible();
}

describe("EDS · «Это дубль ВХ-…» (EDS-DUP)", () => {
  it("делопроизводитель закрывает письмо как дубль: статус «Дубль», ссылка на оригинал, журнал", async () => {
    await openCard("registrar@demo.example", "ВХ-108/26");

    fireEvent.click(screen.getByRole("button", { name: "Это дубль" }));
    const dialog = await screen.findByRole("dialog");
    const submit = within(dialog).getByRole("button", { name: "Отметить дублем" });
    expect(submit).toBeDisabled();
    expect(within(dialog).getByText("Номер ВХ не освобождается")).toBeInTheDocument();
    fireEvent.change(within(dialog).getByLabelText("Номер оригинала"), {
      target: { value: "ВХ-999/26" },
    });
    fireEvent.click(submit);
    expect(await within(dialog).findByText("Входящего с таким номером нет")).toBeInTheDocument();

    fireEvent.change(within(dialog).getByLabelText("Номер оригинала"), {
      target: { value: "ВХ-100/26" },
    });
    fireEvent.change(within(dialog).getByLabelText("Комментарий"), {
      target: { value: "Пришло дважды" },
    });
    // после первой попытки у кнопки уходит значок загрузки (имя «loading Отметить дублем»)
    fireEvent.click(within(dialog).getByRole("button", { name: /Отметить дублем$/ }));

    expect(await screen.findByText("Дубль письма")).toBeVisible();
    expect(screen.getByRole("link", { name: "ВХ-100/26" })).toBeVisible();
    expect(screen.getAllByText("Дубль").length).toBeGreaterThan(0);
    expect(screen.getByText("Дубль ВХ-100/26: Пришло дважды")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Это дубль" })).toBeNull();
  });

  it("у письма с резолюцией — подтверждение отмены поручений", async () => {
    await openCard("registrar@demo.example", "ВХ-100/26");

    fireEvent.click(screen.getByRole("button", { name: "Это дубль" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("Номер оригинала"), {
      target: { value: "ВХ-108/26" },
    });
    const submit = within(dialog).getByRole("button", { name: "Отметить дублем" });
    expect(submit).toBeDisabled();
    fireEvent.click(within(dialog).getByRole("checkbox", { name: /Резолюция уже наложена/ }));
    expect(submit).toBeEnabled();
  });

  it("без раздела регистрации кнопки нет", async () => {
    await openCard("manager@demo.example", "ВХ-108/26");
    expect(screen.queryByRole("button", { name: "Это дубль" })).toBeNull();
  });
});
