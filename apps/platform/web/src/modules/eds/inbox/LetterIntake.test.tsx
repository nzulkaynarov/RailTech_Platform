import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderAt, setupLetterTests, signIn } from "../../../test/lettersKit";

setupLetterTests();

async function openCard(email: string, number: string) {
  signIn(email);
  renderAt(`/eds/inbox/${number}`);
  expect(await screen.findByRole("heading", { level: 1, name: `Письмо ${number}` })).toBeVisible();
}

/** Текст причины, на которую ссылается кнопка через `aria-describedby` */
function reasonOf(button: HTMLElement): string | null {
  const id = button.getAttribute("aria-describedby");
  return id ? (document.getElementById(id)?.textContent ?? null) : null;
}

describe("ВХОД-1 · «Заявка клиента» и «Подключение партнёра» на карточке письма", () => {
  it("у кого есть оба права, оба действия видны сразу — без резолюции и без меню «Ещё»", async () => {
    await openCard("universal@demo.example", "ВХ-108/26");

    const request = screen.getByRole("button", { name: "Заявка клиента" });
    const partner = screen.getByRole("button", { name: "Подключение партнёра" });
    expect(request).toBeEnabled();
    expect(partner).toBeEnabled();
    expect(reasonOf(request)).toBeNull();
    expect(screen.queryByRole("button", { name: "Ещё" })).toBeNull();
  });

  it("«Заявка клиента» открывает форму заявки с файлом письма и названием отправителя", async () => {
    await openCard("manager@demo.example", "ВХ-108/26");

    fireEvent.click(screen.getByRole("button", { name: "Заявка клиента" }));
    const sheet = await screen.findByRole("dialog", { name: /ВХ-108\/26: заявка клиента/ });
    expect(within(sheet).getByText("Название компании")).toBeVisible();
  });

  it("«Подключение партнёра» открывает форму с полем компании", async () => {
    await openCard("universal@demo.example", "ВХ-108/26");

    fireEvent.click(screen.getByRole("button", { name: "Подключение партнёра" }));
    const form = await screen.findByRole("dialog", { name: "ВХ-108/26: подключение партнёра" });
    expect(within(form).getByLabelText("Компания")).toBeVisible();
  });

  it("у письма, по которому заявка уже есть, действие стоит на месте и называет причину", async () => {
    await openCard("manager@demo.example", "ВХ-104/26");

    const request = screen.getByRole("button", { name: "Заявка клиента" });
    expect(request).toBeDisabled();
    expect(reasonOf(request)).toBe("По письму уже есть заявка ЗВ-2026-104.");
    expect(screen.getByRole("button", { name: "Подключение партнёра" })).toBeDisabled();
  });

  it("менеджеру без права на снабжение «Подключение партнёра» называет причину", async () => {
    await openCard("manager@demo.example", "ВХ-108/26");

    const partner = screen.getByRole("button", { name: "Подключение партнёра" });
    expect(partner).toBeDisabled();
    expect(reasonOf(partner)).toBe(
      "Нет доступа к снабжению: заявку на подключение создать нельзя.",
    );
    expect(screen.getByRole("button", { name: "Заявка клиента" })).toBeEnabled();
  });

  it("у письма с заявкой «Подключение партнёра» остаётся доступным тем, у кого есть право", async () => {
    await openCard("universal@demo.example", "ВХ-104/26");

    expect(screen.getByRole("button", { name: "Подключение партнёра" })).toBeEnabled();
    expect(reasonOf(screen.getByRole("button", { name: "Заявка клиента" }))).toBe(
      "По письму уже есть заявка ЗВ-2026-104.",
    );
  });

  it("без права на клиентов кнопка серая только с причиной", async () => {
    await openCard("registrar@demo.example", "ВХ-108/26");

    const request = screen.getByRole("button", { name: "Заявка клиента" });
    expect(request).toBeDisabled();
    expect(reasonOf(request)).toBe("Нет доступа к разделу «Клиенты»: заявку создать нельзя.");
  });
});
