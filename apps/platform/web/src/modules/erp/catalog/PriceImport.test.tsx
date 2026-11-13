import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { chooseOption } from "../../../test/fields";
import {
  findModal,
  modalClosed,
  renderAt,
  findPartnerCard,
  partnerPath,
  setupCatalogTests,
  signIn,
} from "../../../test/catalogKit";

setupCatalogTests();

// CAT-1: партнёр, загрузка прайса (проверка → отчёт → применить), изменения карточки от партнёров, публикация.
// Названия заводов выдуманы.

async function open(email: string, search: string) {
  signIn(email);
  renderAt(`/erp/catalog${search}`);
  const heading = search.includes("import") ? "Загрузка прайса" : "Товары";
  expect(await screen.findByRole("heading", { level: 1, name: heading })).toBeVisible();
}

const xlsx = () =>
  new File(["PK\u0003\u0004 price"], "werk-nordlicht.xlsx", {
    type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  });

describe("Загрузка прайса партнёра", () => {
  it("новый иностранный партнёр без ИНН, проверка ничего не пишет, «Применить» загружает", async () => {
    await open("supply@demo.example", "?part=import");

    fireEvent.click(await screen.findByRole("button", { name: "Новый партнёр" }));
    // форма секциями в боковом окне (§4.1a)
    const form = await screen.findByRole("region", { name: "Новый партнёр" });
    fireEvent.change(within(form).getByLabelText("Название"), {
      target: { value: "Werk Nordlicht GmbH" },
    });
    await chooseOption(within(form).getByLabelText("Страна"), "Германия");
    fireEvent.change(within(form).getByLabelText("Рег. номер"), {
      target: { value: "HRB 000001" },
    });
    fireEvent.click(within(form).getByRole("button", { name: "Добавить" }));
    await waitFor(() => {
      expect(screen.queryByRole("region", { name: "Новый партнёр" })).toBeNull();
    });

    fireEvent.change(screen.getByLabelText("Файл прайса"), { target: { files: [xlsx()] } });
    const check = screen.getByRole("button", { name: "Проверить" });
    await waitFor(() => {
      expect(check).toBeEnabled();
    });
    fireEvent.click(check);

    expect(await screen.findByText("Проверка: ничего не записано")).toBeVisible();
    expect(screen.getByText("Неизвестная валюта «XYZ»")).toBeVisible();
    expect(screen.getByText("Кабель силовой ВВГнг-LS 3×2,5")).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "Применить" }));
    expect(await screen.findByText("Прайс загружен")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Открыть позиции на одобрении" }));

    const cable = await screen.findByRole("button", { name: /Открыть позицию Кабель силовой/ });
    expect(screen.getByRole("checkbox", { name: "Изменения на одобрении" })).toBeChecked();
    fireEvent.click(cable);
    const drawer = await screen.findByRole("dialog", { name: "Кабель силовой ВВГнг 3×2,5" });
    expect(await within(drawer).findByText("Изменения от партнёров")).toBeVisible();
    expect(
      within(drawer).getByText("Werk Nordlicht GmbH", { selector: ".pf-cat-sub" }),
    ).toBeVisible();
    fireEvent.click(
      within(drawer).getByRole("button", { name: "Отклонить изменение: Наименование" }),
    );
    await waitFor(() => {
      expect(within(drawer).queryByText("Изменения от партнёров")).toBeNull();
    });
    expect(screen.getByRole("dialog", { name: "Кабель силовой ВВГнг 3×2,5" })).toBeVisible();
  });

  it("без права на цены партнёров загрузки нет", async () => {
    await open("manager@demo.example", "?part=import");
    expect(await screen.findByText("Загрузка прайса недоступна")).toBeVisible();
  });
});

describe("Партнёр и его цена", () => {
  it("снабженец добавляет цену с Incoterms и видит историю", async () => {
    signIn("supply@demo.example");
    renderAt(partnerPath("3"));
    const drawer = await findPartnerCard("ИП «Восточный склад»");
    fireEvent.click(await within(drawer).findByRole("button", { name: "Добавить цену" }));
    const form = await findModal(/Цена партнёра/);
    await chooseOption(within(form).getByLabelText("Позиция"), "Реле защиты РЗ-1");
    fireEvent.change(within(form).getByLabelText(/Цена закупки/), { target: { value: "295" } });
    await chooseOption(within(form).getByLabelText("Базис поставки (Incoterms)"), "FCA");
    fireEvent.click(within(form).getByRole("button", { name: "Добавить" }));
    await modalClosed(/Цена партнёра/);

    fireEvent.click(
      await within(drawer).findByRole("button", {
        name: "История цены по позиции Реле защиты РЗ-1",
      }),
    );
    const history = await findModal(/История цены/);
    expect(await within(history).findByText(/295 сум/)).toBeInTheDocument();
    expect(within(history).getByText("вручную")).toBeInTheDocument();
  });
});

describe("Карточка: изготовитель, артикул, ТН ВЭД и публикация", () => {
  it("неполную карточку не опубликовать — сказано, чего не хватает", async () => {
    await open("supply@demo.example", "?item=5");
    const drawer = await screen.findByRole("dialog", { name: "Пусконаладочные работы" });
    expect(
      await within(drawer).findByText(/Для публикации заполните: категория, код ТН ВЭД/),
    ).toBeVisible();
    expect(within(drawer).getByRole("button", { name: "Опубликовать" })).toBeDisabled();
  });
});
