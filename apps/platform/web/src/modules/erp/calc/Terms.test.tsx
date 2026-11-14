import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderAt, setupCalcTests, signIn } from "../../../test/calcKit";

setupCalcTests();

const NUMBER = "ЗВ-2026-097";
const PATH = `/erp/calc/${encodeURIComponent(NUMBER)}`;

async function openCalc(email: string) {
  signIn(email);
  renderAt(PATH);
  expect(
    await screen.findByRole("heading", { level: 1, name: `Расчёт по заявке ${NUMBER}` }),
  ).toBeVisible();
  return screen.getByRole("heading", { level: 2, name: "Условия КП" }).closest(".ant-card");
}

describe("Расчёт · условия КП (план 0.5)", () => {
  it("новый КП показывает условия из настроек компании, срок поставки — по строкам", async () => {
    const card = await openCalc("supply@demo.example");
    if (!(card instanceof HTMLElement)) throw new Error("нет карточки условий");
    expect(within(card).getByText("100% предоплата")).toBeVisible();
    expect(within(card).getByText("31.12.2026")).toBeVisible();
    expect(within(card).getByText(/^По строкам: \d+ дн\.$/)).toBeVisible();
  });

  it("правка в боковом окне: условия оплаты и срок поставки сохраняются в карточке", async () => {
    await openCalc("supply@demo.example");
    fireEvent.click(screen.getByRole("button", { name: "Изменить" }));
    const form = await screen.findByRole("region", { name: "Условия КП" });
    fireEvent.change(within(form).getByLabelText("Условия оплаты"), {
      target: { value: "50% предоплата, 50% по поставке" },
    });
    fireEvent.change(within(form).getByLabelText("Срок поставки, дней"), {
      target: { value: "60" },
    });
    fireEvent.click(within(form).getByRole("button", { name: "Сохранить" }));
    await waitFor(() => {
      expect(screen.queryByRole("region", { name: "Условия КП" })).toBeNull();
    });
    expect(await screen.findByText("50% предоплата, 50% по поставке")).toBeVisible();
    expect(screen.getByText("60 дн.")).toBeVisible();
  });

  it("без права на расчёт — только просмотр", async () => {
    await openCalc("accountant@demo.example");
    expect(screen.getByText("100% предоплата")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Изменить" })).toBeNull();
  });
});
