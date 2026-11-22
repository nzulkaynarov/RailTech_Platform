import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderAt, setupCatalogTests, signIn } from "../../../test/catalogKit";

setupCatalogTests();

/** Галочка (`StepSections`): в кружке svg, и шаг не помечен «нужно исправить» (там тоже svg — знак тревоги). */
const ticked = (head: HTMLElement) =>
  head.querySelector(".pf-fstep-badge svg") !== null &&
  head.closest("li")?.getAttribute("data-invalid") === null;

describe("Новый партнёр · галочки шагов (Х-18)", () => {
  it("шаг «Контакт» с неверной почтой не получает галочку; с верной — получает", async () => {
    signIn("supply@demo.example");
    renderAt("/erp/catalog?part=import");
    fireEvent.click(await screen.findByRole("button", { name: "Новый партнёр" }));
    const form = await screen.findByRole("region", { name: "Новый партнёр" });
    const head = (name: RegExp) => within(form).getByRole("button", { name });

    fireEvent.click(head(/^Контакт/));
    fireEvent.change(within(form).getByLabelText("Почта"), { target: { value: "not-an-email" } });
    fireEvent.click(head(/^Компания/));
    expect(ticked(head(/^Контакт/))).toBe(false);

    fireEvent.click(head(/^Контакт/));
    fireEvent.change(within(form).getByLabelText("Почта"), {
      target: { value: "sales@partner.example" },
    });
    fireEvent.click(head(/^Компания/));
    expect(ticked(head(/^Контакт/))).toBe(true);
  });

  it("шаг «Компания» с ИНН не из 9 цифр не получает галочку", async () => {
    signIn("supply@demo.example");
    renderAt("/erp/catalog?part=import");
    fireEvent.click(await screen.findByRole("button", { name: "Новый партнёр" }));
    const form = await screen.findByRole("region", { name: "Новый партнёр" });
    fireEvent.change(within(form).getByLabelText("Название"), { target: { value: "Демо Сталь" } });
    fireEvent.change(within(form).getByLabelText("ИНН"), { target: { value: "12345" } });
    fireEvent.click(within(form).getByRole("button", { name: /^Контакт/ }));
    expect(ticked(within(form).getByRole("button", { name: /^Компания/ }))).toBe(false);
  });
});
