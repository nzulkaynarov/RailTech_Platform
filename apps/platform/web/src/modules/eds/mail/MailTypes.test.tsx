import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { ROLE_ID } from "../../../mocks/fixtures/roles";
import { readEmployees, writeEmployees } from "../../../mocks/fixtures/employees";
import { readRules } from "../../../mocks/mailTypes";
import { resetInboundMailMock } from "../../../mocks/inboundMail";
import { renderAt, setupLetterTests, signIn } from "../../../test/lettersKit";

setupLetterTests();
beforeEach(() => {
  resetInboundMailMock();
});

const REGISTRAR = "registrar@demo.example";
// Администратор, которому в «Оргструктуре» выдали ещё и роль первой линии почты, — создаёт правило из карточки.
const ADMIN = "admin@demo.example";
const heading = (name: string) => screen.findByRole("heading", { level: 1, name });
const listOf = (name: string) => screen.findByRole("list", { name });

describe("Типы входящих писем: тег, фильтр, основная кнопка (MAIL-TYPES)", () => {
  it("в списке у письма тег типа; фильтр по типу оставляет только такие письма, счётчики вкладок не меняются", async () => {
    signIn(REGISTRAR);
    renderAt("/eds/mail");
    const list = await listOf("Письма, ждущие разбора");
    expect(within(list).getByText("КП или прайс поставщика")).toBeVisible();
    expect(within(list).getByText("Рассылка")).toBeVisible();
    expect(screen.getByRole("tab", { name: "Новые · 6" })).toBeVisible();

    fireEvent.mouseDown(screen.getByRole("combobox", { name: "Тип письма" }));
    fireEvent.click(await screen.findByTitle("Рассылка"));
    await waitFor(() => {
      expect(
        within(screen.getByRole("list", { name: "Письма, ждущие разбора" })).getAllByRole(
          "listitem",
        ),
      ).toHaveLength(1);
    });
    expect(screen.getByRole("tab", { name: "Новые · 6" })).toBeVisible();
    expect(screen.getByText("Скидки недели на канцтовары")).toBeVisible();
  });

  it("«КП поставщика»: основная кнопка — «Загрузить прайс»; письмо закрывает человек, когда прайс загружен", async () => {
    signIn(REGISTRAR);
    renderAt("/eds/mail/28");
    expect(await heading("Коммерческое предложение на скрепления КБ-65")).toBeVisible();
    const primary = screen.getByRole("button", { name: "Загрузить прайс" });
    expect(primary).toHaveClass("ant-btn-primary");
    // остальные действия — в меню, а не рядом
    expect(screen.queryByRole("button", { name: "Создать лид" })).toBeNull();
    fireEvent.click(primary);
    expect(screen.getByRole("link", { name: "Открыть загрузку прайса" })).toHaveAttribute(
      "href",
      "/erp/catalog?part=import",
    );
    expect(screen.getByRole("group", { name: "Что произойдёт" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Прайс загружен — убрать из очереди" }));
    expect(await screen.findByText("Письмо разобрано: прайс загружен")).toBeVisible();
    const list = await listOf("Письма, ждущие разбора");
    expect(within(list).queryByText("Коммерческое предложение на скрепления КБ-65")).toBeNull();

    // письмо не потеряно: оно в «Разобранных» с итогом
    fireEvent.click(screen.getByRole("tab", { name: /Разобранные/ }));
    const done = await listOf("Разобранные письма");
    const link = await within(done).findByText("Коммерческое предложение на скрепления КБ-65");
    expect(link.closest("li")).toHaveTextContent("Прайс загружен");
  });

  it("человек меняет тип одним щелчком: основная кнопка меняется, в журнале — запись", async () => {
    signIn(REGISTRAR);
    renderAt("/eds/mail/28");
    await heading("Коммерческое предложение на скрепления КБ-65");
    expect(screen.getByText("предложил помощник")).toBeVisible();
    fireEvent.mouseDown(screen.getByRole("combobox", { name: "Сменить тип" }));
    fireEvent.click(await screen.findByTitle("Рассылка"));
    expect(await screen.findByText("Тип изменён")).toBeVisible();
    expect(await screen.findByRole("button", { name: "В архив как рассылку" })).toHaveClass(
      "ant-btn-primary",
    );
    expect(screen.getByText("выбрал сотрудник")).toBeVisible();
    expect(await screen.findByText(/сменил тип — Рассылка/)).toBeVisible();
  });

  it("счёт поставщика: «Передать бухгалтеру» — письмо уходит выбранному сотруднику, из «Новых» пропадает", async () => {
    signIn(REGISTRAR);
    renderAt("/eds/mail/17");
    await heading("Акт сверки за октябрь");
    fireEvent.click(await screen.findByRole("button", { name: "Передать бухгалтеру" }));
    expect(await screen.findByText("Бухгалтер Демо")).toBeVisible();
    expect(screen.getByRole("group", { name: "Что произойдёт" })).toBeVisible();
    const [, confirm] = screen.getAllByRole("button", { name: "Передать бухгалтеру" });
    fireEvent.click(confirm ?? screen.getByRole("button", { name: "Передать" }));
    expect(await screen.findByText("Письмо передано: Бухгалтер Демо")).toBeVisible();
    const list = await listOf("Письма, ждущие разбора");
    expect(within(list).queryByText("Акт сверки за октябрь")).toBeNull();
  });

  it("рассылка из меню действий: «В Подозрительные» уносит письмо во вкладку «Подозрительные»", async () => {
    signIn(REGISTRAR);
    renderAt("/eds/mail/28");
    await heading("Коммерческое предложение на скрепления КБ-65");
    fireEvent.click(screen.getByRole("button", { name: /Другое действие/ }));
    fireEvent.click(await screen.findByRole("menuitem", { name: "В «Подозрительные»" }));
    fireEvent.click(screen.getByRole("button", { name: "В «Подозрительные»" }));
    expect(await screen.findByText("Письмо в «Подозрительных»")).toBeVisible();
    fireEvent.click(await screen.findByRole("tab", { name: /Подозрительные/ }));
    const spam = await listOf("Подозрительные письма");
    expect(
      await within(spam).findByText("Коммерческое предложение на скрепления КБ-65"),
    ).toBeVisible();
  });

  it("создание правила из карточки: «Всегда считать письма от этого домена …» — только у администратора", async () => {
    signIn(REGISTRAR);
    renderAt("/eds/mail/29");
    await heading("Требование о предоставлении документов");
    // без типа правила нет; сменив тип, делопроизводитель правило создать не может — это настройка администратора
    fireEvent.mouseDown(screen.getByRole("combobox", { name: "Сменить тип" }));
    fireEvent.click(await screen.findByTitle("Официальное письмо (госорган, банк, налоговая)"));
    expect(await screen.findByText("Тип изменён")).toBeVisible();
    expect(screen.queryByRole("button", { name: /Всегда считать письма/ })).toBeNull();
  });
});

describe("Правило отправителя из карточки (MAIL-TYPES, администратор)", () => {
  beforeEach(() => {
    writeEmployees(
      readEmployees().map((e) =>
        e.email === ADMIN ? { ...e, role_ids: [...e.role_ids, ROLE_ID.REGISTRAR] } : e,
      ),
    );
  });

  it("предложенный помощником тип подтверждается правилом: дальше письма домена получают тип сами", async () => {
    signIn(ADMIN);
    renderAt("/eds/mail/28");
    await heading("Коммерческое предложение на скрепления КБ-65");
    fireEvent.click(
      await screen.findByRole("button", {
        name: "Всегда считать письма от rail-parts-demo.example — «КП или прайс поставщика»",
      }),
    );
    expect((await screen.findAllByText(/Правило создано/)).length).toBeGreaterThan(0);
    expect(readRules().map((r) => [r.pattern, r.type_code])).toEqual([
      ["rail-parts-demo.example", "supplier_price"],
    ]);
    // тип письма теперь «по правилу отправителя», второго правила из карточки не создать
    expect(await screen.findByText("по правилу отправителя")).toBeVisible();
    expect(screen.queryByRole("button", { name: /Всегда считать письма/ })).toBeNull();
  });

  it("выбор человека правило не перебивает; то же правило второй раз — «уже есть» словами", async () => {
    signIn(ADMIN);
    renderAt("/eds/mail/29");
    await heading("Требование о предоставлении документов");
    fireEvent.mouseDown(screen.getByRole("combobox", { name: "Сменить тип" }));
    fireEvent.click(await screen.findByTitle("Официальное письмо (госорган, банк, налоговая)"));
    await screen.findByText("Тип изменён");
    const name =
      "Всегда считать письма от soliq.example — «Официальное письмо (госорган, банк, налоговая)»";
    await screen.findByText("выбрал сотрудник");
    fireEvent.click(await screen.findByRole("button", { name }));
    expect((await screen.findAllByText(/Правило создано/)).length).toBeGreaterThan(0);
    expect(screen.getByText("выбрал сотрудник")).toBeVisible();
    fireEvent.click(await screen.findByText(name));
    expect(await screen.findByText("Такое правило уже есть.")).toBeVisible();
  });
});
