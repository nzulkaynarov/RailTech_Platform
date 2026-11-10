import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { chooseOption } from "../../../test/fields";
import { server } from "../../../test/server";
import { readErpCatalog } from "../../../mocks/fixtures/erpCatalog";
import {
  findModal,
  modalClosed,
  renderAt,
  setupCatalogTests,
  signIn,
} from "../../../test/catalogKit";

setupCatalogTests();

/** Очередь проверки партнёров (PART-3): список, срок, возврат с причинами, публикация, цены партнёра. */
async function openQueue(email = "supply@demo.example") {
  signIn(email);
  renderAt("/erp/catalog?review=waiting");
  return screen.findByRole("table", { name: "Очередь проверки партнёров" });
}

describe("Очередь проверки: список", () => {
  it("старые отправки сверху, партнёр, срок словом и полнота; счётчик на переключателе", async () => {
    const table = await openQueue();
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(3);
    expect(within(rows[0] as HTMLElement).getByText("Болт М20×80 оцинкованный")).toBeVisible();
    expect(within(rows[0] as HTMLElement).getByText("АО «Южный Металл»")).toBeVisible();
    expect(within(rows[0] as HTMLElement).getByText("Просрочено")).toBeVisible();
    expect(within(rows[0] as HTMLElement).getByText("75 %")).toBeVisible();
    expect(within(rows[1] as HTMLElement).getByText("Хомут кабельный 200 мм")).toBeVisible();
    expect(within(rows[2] as HTMLElement).getByText("Шайба пружинная 20")).toBeVisible();
    expect(within(rows[2] as HTMLElement).getByText("В срок")).toBeVisible();
    expect(await screen.findByText("Ждут проверки · 3")).toBeVisible();
    expect(screen.getByRole("radio", { name: "Все позиции" })).toBeInTheDocument();
  });

  it("пустая очередь говорит словами, что делать", async () => {
    server.use(
      http.get("*/erp/catalog/items", () =>
        HttpResponse.json({ items: [], total: 0, page: 1, page_size: 25 }),
      ),
    );
    signIn("supply@demo.example");
    renderAt("/erp/catalog?review=waiting");
    expect(await screen.findByText("Очередь пуста")).toBeVisible();
  });
});

describe("Очередь проверки: решение в карточке", () => {
  it("карточка без кода ТН ВЭД: «Опубликовать» недоступна и сказано, чего не хватает", async () => {
    signIn("supply@demo.example");
    renderAt("/erp/catalog?review=waiting&item=6");
    const drawer = await screen.findByRole("dialog", { name: "Болт М20×80 оцинкованный" });
    expect(await within(drawer).findByText("Проверка карточки")).toBeVisible();
    expect(within(drawer).getByRole("button", { name: "Опубликовать" })).toBeDisabled();
    expect(within(drawer).getByText(/Для публикации заполните: код ТН ВЭД/)).toBeVisible();
    expect(within(drawer).getByRole("button", { name: "Вернуть партнёру" })).toBeEnabled();
  });

  it("публикация полной карточки убирает её из очереди", async () => {
    signIn("supply@demo.example");
    renderAt("/erp/catalog?review=waiting&item=7");
    const drawer = await screen.findByRole("dialog", { name: "Шайба пружинная 20" });
    fireEvent.click(await within(drawer).findByRole("button", { name: "Опубликовать" }));
    await waitFor(() => {
      expect(readErpCatalog().items.find((i) => i.id === "7")?.status).toBe("PUBLISHED");
    });
    expect(await screen.findByText("Ждут проверки · 2")).toBeVisible();
  });

  it("возврат: без причины кнопка недоступна, замечание по полю собирается и уходит в BFF", async () => {
    let sent: unknown = null;
    server.use(
      http.post("*/erp/catalog/items/:id/return", async ({ request }) => {
        sent = await request.clone().json();
        return undefined;
      }),
    );
    signIn("supply@demo.example");
    renderAt("/erp/catalog?review=waiting&item=6");
    const drawer = await screen.findByRole("dialog", { name: "Болт М20×80 оцинкованный" });
    fireEvent.click(await within(drawer).findByRole("button", { name: "Вернуть партнёру" }));
    const modal = await findModal("Вернуть карточку партнёру");
    const ok = within(modal).getByRole("button", { name: "Вернуть" });
    expect(ok).toBeDisabled();

    fireEvent.click(within(modal).getByRole("button", { name: "Добавить замечание" }));
    // замечание заполнено наполовину — отправлять нельзя
    await chooseOption(
      within(modal).getByRole("combobox", { name: "Поле 1" }),
      "Артикул изготовителя",
    );
    expect(ok).toBeDisabled();
    fireEvent.change(within(modal).getByLabelText("Замечание 1"), {
      target: { value: "Укажите артикул по шильдику" },
    });
    expect(ok).toBeEnabled();
    fireEvent.change(within(modal).getByLabelText("Общий комментарий"), {
      target: { value: "Не хватает данных" },
    });
    fireEvent.click(ok);

    await modalClosed("Вернуть карточку партнёру");
    expect(sent).toEqual({
      reason: "Не хватает данных",
      issues: [{ field: "manufacturer_part_number", comment: "Укажите артикул по шильдику" }],
    });
    expect(readErpCatalog().items.find((i) => i.id === "6")?.status).toBe("RETURNED");
    expect(await screen.findByText("Ждут проверки · 2")).toBeVisible();
  });

  it("только общий комментарий — достаточно; замечание можно убрать", async () => {
    signIn("supply@demo.example");
    renderAt("/erp/catalog?review=waiting&item=6");
    const drawer = await screen.findByRole("dialog", { name: "Болт М20×80 оцинкованный" });
    fireEvent.click(await within(drawer).findByRole("button", { name: "Вернуть партнёру" }));
    const modal = await findModal("Вернуть карточку партнёру");
    fireEvent.click(within(modal).getByRole("button", { name: "Добавить замечание" }));
    fireEvent.click(within(modal).getByRole("button", { name: "Убрать замечание 1" }));
    expect(within(modal).queryByLabelText("Замечание 1")).not.toBeInTheDocument();
    fireEvent.change(within(modal).getByLabelText("Общий комментарий"), {
      target: { value: "Нет фото" },
    });
    expect(within(modal).getByRole("button", { name: "Вернуть" })).toBeEnabled();
  });

  it("карточку уже решили: текст отказа говорит об этом, карточка не меняется", async () => {
    server.use(
      http.post("*/erp/catalog/items/:id/return", () =>
        HttpResponse.json(
          {
            code: "CONFLICT",
            message: "x",
            source: "erp",
            details: { reason: "product_not_on_review", backend_status: 409 },
          },
          { status: 409 },
        ),
      ),
    );
    signIn("supply@demo.example");
    renderAt("/erp/catalog?review=waiting&item=6");
    const drawer = await screen.findByRole("dialog", { name: "Болт М20×80 оцинкованный" });
    fireEvent.click(await within(drawer).findByRole("button", { name: "Вернуть партнёру" }));
    const modal = await findModal("Вернуть карточку партнёру");
    fireEvent.change(within(modal).getByLabelText("Общий комментарий"), {
      target: { value: "Поздно" },
    });
    fireEvent.click(within(modal).getByRole("button", { name: "Вернуть" }));
    expect(await within(modal).findByText(/Карточка уже не на проверке/)).toBeInTheDocument();
    expect(readErpCatalog().items.find((i) => i.id === "6")?.status).toBe("REVIEW");
  });

  it("правки партнёра к опубликованной карточке решаются по полю в том же потоке", async () => {
    signIn("supply@demo.example");
    renderAt("/erp/catalog?review=waiting&item=8");
    const drawer = await screen.findByRole("dialog", { name: "Хомут кабельный 200 мм" });
    expect(
      await within(drawer).findByText(/предложил правки к опубликованной карточке/),
    ).toBeVisible();
    expect(within(drawer).queryByRole("button", { name: "Вернуть партнёру" })).toBeNull();
    fireEvent.click(
      await within(drawer).findByRole("button", { name: "Принять изменение: Описание" }),
    );
    await waitFor(() => {
      expect(readErpCatalog().items.find((i) => i.id === "8")?.proposals).toHaveLength(0);
    });
    expect(await screen.findByText("Ждут проверки · 2")).toBeVisible();
  });

  it("менеджеру с правом чтения кнопок решения нет", async () => {
    signIn("manager@demo.example");
    renderAt("/erp/catalog?review=waiting&item=7");
    const drawer = await screen.findByRole("dialog", { name: "Шайба пружинная 20" });
    await within(drawer).findByText("Проверка карточки");
    expect(within(drawer).queryByRole("button", { name: "Опубликовать" })).toBeNull();
    expect(within(drawer).queryByRole("button", { name: "Вернуть партнёру" })).toBeNull();
  });
});

describe("Цены партнёра в каталоге", () => {
  it("«Цена в каталоге» в карточке следует настройке партнёра", async () => {
    signIn("supply@demo.example");
    renderAt("/erp/catalog?item=7");
    const drawer = await screen.findByRole("dialog", { name: "Шайба пружинная 20" });
    expect(await within(drawer).findByText("по запросу")).toBeVisible();
    expect(within(drawer).getByText("по политике каталога")).toBeVisible();
  });

  it("в блоке «Доступ в кабинет» цены партнёра переключаются и сохраняются", async () => {
    signIn("supply@demo.example");
    renderAt("/erp/catalog?part=suppliers&supplier=2");
    const select = await screen.findByRole("combobox", { name: "Цены товаров в каталоге" });
    expect(select).toBeEnabled();
    await chooseOption(select, "Показывать");
    await waitFor(() => {
      expect(
        screen.getByText("Показывать", { selector: ".ant-select-selection-item" }),
      ).toBeVisible();
    });
  });
});
