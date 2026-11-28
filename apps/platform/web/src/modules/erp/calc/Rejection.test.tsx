import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderAt, setupCalcTests, signIn } from "../../../test/calcKit";

setupCalcTests();

const REJECTED = "ЗВ-2026-109";

async function openCalc(email: string, number: string) {
  signIn(email);
  renderAt(`/erp/calc/${encodeURIComponent(number)}`);
  expect(
    await screen.findByRole("heading", { level: 1, name: `Расчёт по заявке ${number}` }),
  ).toBeVisible();
}

describe("Расчёт · клиент отклонил КП (D26G-3)", () => {
  it("называет клиента и причину и предлагает два действия; «Новая версия КП» открывает расчёт версии 2", async () => {
    await openCalc("universal@demo.example", REJECTED);
    expect(
      screen.getByText(
        "Клиент отклонил КП КП-2026/119 (версия 1): «Дорого: у конкурента на 7 % ниже, просим пересмотреть цену привода».",
      ),
    ).toBeVisible();
    expect(screen.getByText("КП отклонено клиентом")).toBeVisible();
    expect(screen.queryByText(/Директор отклонил КП/)).toBeNull();
    expect(screen.getByRole("button", { name: "Закрыть заявку" })).toBeEnabled();

    fireEvent.click(screen.getByRole("button", { name: "Новая версия КП" }));

    await waitFor(() => {
      expect(screen.getByText("В работе")).toBeVisible();
    });
    expect(screen.queryByText(/Клиент отклонил КП/)).toBeNull();
    expect(screen.getByRole("button", { name: /Подтвердить строку «Привод/ })).toBeVisible();
  });

  it("«Закрыть заявку» после отказа клиента — один путь, причина «Клиент передумал» выбрана заранее", async () => {
    await openCalc("universal@demo.example", REJECTED);
    expect(screen.queryByRole("button", { name: "Отказ по заявке" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Закрыть заявку" }));
    const dialog = await screen.findByRole("dialog", { name: `Закрыть заявку ${REJECTED}` });
    expect(await within(dialog).findByRole("radio", { name: "Клиент передумал" })).toBeChecked();
    expect(within(dialog).getByRole("radio", { name: "Тест" })).toBeDisabled();
    fireEvent.click(within(dialog).getByRole("button", { name: "Закрыть заявку" }));
    await waitFor(() => {
      expect(screen.getByText("Заявка закрыта: Клиент передумал")).toBeVisible();
    });
    expect(screen.queryByRole("button", { name: "Новая версия КП" })).toBeNull();
  });

  it("без полного доступа к расчёту — причина видна, действий нет", async () => {
    await openCalc("accountant@demo.example", REJECTED);
    expect(screen.getByText(/Клиент отклонил КП КП-2026\/119/)).toBeVisible();
    expect(screen.queryByRole("button", { name: "Новая версия КП" })).toBeNull();
  });
});

describe("Расчёт · цена клиенту и маржа (РАСЧ-3)", () => {
  it("введённая маржа строки даёт цену: себестоимость / (1 − маржа), вверх до шага", async () => {
    await openCalc("supply@demo.example", "ЗВ-2026-097");
    const name = "Перевод стрелочный Р65 марки 1/11";
    const margin = screen.getByLabelText(`Маржа, %: ${name}`);
    fireEvent.change(margin, { target: { value: "20" } });
    fireEvent.blur(margin);
    await waitFor(() => {
      expect(
        screen.getByLabelText<HTMLInputElement>(`Цена клиенту без НДС за единицу для «${name}»`)
          .value,
      ).toMatch(/^112\s500\s000/);
    });
  });

  it("введённая цена помечается «Цена вручную», «вернуть N %» считает её от маржи снова", async () => {
    await openCalc("supply@demo.example", "ЗВ-2026-097");
    const name = "Перевод стрелочный Р65 марки 1/11";
    const price = () =>
      screen.getByLabelText<HTMLInputElement>(`Цена клиенту без НДС за единицу для «${name}»`);
    expect(screen.queryByTestId("price-manual")).toBeNull();
    fireEvent.change(price(), { target: { value: "101000000" } });
    fireEvent.blur(price());
    const mark = await screen.findByTestId("price-manual");
    expect(mark).toHaveTextContent("Цена вручную");
    fireEvent.click(
      within(mark).getByRole("button", { name: `Вернуть цену строки «${name}» к марже` }),
    );
    await waitFor(() => {
      expect(screen.queryByTestId("price-manual")).toBeNull();
    });
    // 90 000 000 / (1 − 20 %) = 112 500 000
    expect(price().value).toMatch(/^112\s500\s000/);
    expect(screen.getByTestId("price-rule")).toHaveTextContent("маржа 20 %");
  });
});
