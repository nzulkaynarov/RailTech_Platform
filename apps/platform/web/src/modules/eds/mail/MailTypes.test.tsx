import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
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
const SUPPLY = "supply@demo.example";
const ACCOUNTANT = "accountant@demo.example";
// Администратор, которому в «Оргструктуре» выдали ещё и роль первой линии почты, — создаёт правило из карточки.
const ADMIN = "admin@demo.example";
/** Сотрудник «Делопроизводитель» с ещё одной ролью — как после выдачи роли в Оргструктуре. */
function registrarWith(roleId: string) {
  return {
    id: "u-demo-registrar",
    name: "Демо Канцелярова",
    initials: "ДК",
    email: REGISTRAR,
    position: "Делопроизводитель",
    role_ids: [ROLE_ID.REGISTRAR, roleId],
    access: { crm: true, erp: true },
    status: "active" as const,
    telegram_linked: false,
    erp_sync: "ok" as const,
  };
}
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

  it("«КП поставщика», у сотрудника нет права на каталог: «Передать на загрузку прайса» — письмо уходит снабженцу", async () => {
    signIn(REGISTRAR);
    renderAt("/eds/mail/28");
    expect(await heading("Коммерческое предложение на скрепления КБ-65")).toBeVisible();
    const primary = screen.getByRole("button", { name: "Передать на загрузку прайса" });
    expect(primary).toHaveClass("ant-btn-primary");
    expect(screen.queryByRole("button", { name: "Загрузить прайс" })).toBeNull();
    fireEvent.click(primary);
    // единственный кандидат — снабженец (право на каталог и цены поставщиков) — подставлен сам
    expect(await screen.findByText("Демо Снабженцев")).toBeVisible();
    expect(screen.getByRole("group", { name: "Что произойдёт" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Передать на загрузку" }));
    expect(
      await screen.findByText("Письмо передано на загрузку прайса: Демо Снабженцев"),
    ).toBeVisible();
    const list = await listOf("Письма, ждущие разбора");
    expect(within(list).queryByText("Коммерческое предложение на скрепления КБ-65")).toBeNull();
  });

  it("«КП поставщика», право на каталог есть: «Загрузить прайс» → «Прайс загружен» → письмо в «Разобранных», его можно вернуть", async () => {
    // делопроизводителю в Оргструктуре выдана и роль снабженца
    writeEmployees([...readEmployees(), registrarWith(ROLE_ID.SUPPLY)]);
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

    // письмо не потеряно: оно в «Разобранных» с итогом, и его можно вернуть в «Новые»
    fireEvent.click(screen.getByRole("tab", { name: /Разобранные/ }));
    const done = await listOf("Разобранные письма");
    const link = await within(done).findByText("Коммерческое предложение на скрепления КБ-65");
    expect(link.closest("li")).toHaveTextContent("Прайс загружен");
    expect(within(done).getAllByRole("button", { name: "Вернуть в Новые" }).length).toBeGreaterThan(
      0,
    );
  });

  it("снабженец (только SUPPLY) закрывает переданное ему письмо: «Прайс загружен — убрать из очереди», письмо уходит из его очереди", async () => {
    signIn(REGISTRAR);
    renderAt("/eds/mail/28");
    await heading("Коммерческое предложение на скрепления КБ-65");
    fireEvent.click(screen.getByRole("button", { name: "Передать на загрузку прайса" }));
    expect(await screen.findByText("Демо Снабженцев")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Передать на загрузку" }));
    expect(
      await screen.findByText("Письмо передано на загрузку прайса: Демо Снабженцев"),
    ).toBeVisible();
    cleanup();

    // то же письмо — у снабженца, у которого нет первой линии: он его видит и закрывает сам
    signIn(SUPPLY);
    renderAt("/eds/my-mail/28");
    await heading("Коммерческое предложение на скрепления КБ-65");
    expect(screen.getByRole("link", { name: "Открыть загрузку прайса" })).toHaveAttribute(
      "href",
      "/erp/catalog?part=import",
    );
    fireEvent.click(screen.getByRole("button", { name: "Прайс загружен — убрать из очереди" }));
    expect(await screen.findByText("Письмо разобрано: прайс загружен")).toBeVisible();
    fireEvent.click(await screen.findByRole("tab", { name: /Все мои/ }));
    const all = await listOf("Все письма");
    expect(
      (await within(all).findByText("Коммерческое предложение на скрепления КБ-65")).closest("li"),
    ).toHaveTextContent("Прайс загружен");
  });

  it("бухгалтер (без первой линии) закрывает переданный ему счёт: «Готово — убрать из очереди»", async () => {
    signIn(REGISTRAR);
    renderAt("/eds/mail/18");
    await heading("Запрос КП на стрелочные переводы");
    fireEvent.mouseDown(screen.getByRole("combobox", { name: "Сменить тип" }));
    fireEvent.click(await screen.findByTitle("Счёт поставщика"));
    fireEvent.click(await screen.findByRole("button", { name: "Передать бухгалтеру" }));
    expect(await screen.findByText("Демо Бухгалтеров")).toBeVisible();
    const [, confirm] = screen.getAllByRole("button", { name: "Передать бухгалтеру" });
    fireEvent.click(confirm ?? screen.getByRole("button", { name: "Передать" }));
    expect(await screen.findByText("Письмо передано: Демо Бухгалтеров")).toBeVisible();
    cleanup();

    signIn(ACCOUNTANT);
    renderAt("/eds/my-mail/18");
    await heading("Запрос КП на стрелочные переводы");
    expect(screen.queryByRole("link", { name: "Открыть загрузку прайса" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Готово — убрать из очереди" }));
    expect(await screen.findByText("Письмо убрано из очереди")).toBeVisible();
    fireEvent.click(await screen.findByRole("tab", { name: /Все мои/ }));
    const all = await listOf("Все письма");
    expect(
      (await within(all).findByText("Запрос КП на стрелочные переводы")).closest("li"),
    ).toHaveTextContent("Обработано");
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
    renderAt("/eds/mail/18");
    await heading("Запрос КП на стрелочные переводы");
    fireEvent.mouseDown(screen.getByRole("combobox", { name: "Сменить тип" }));
    fireEvent.click(await screen.findByTitle("Счёт поставщика"));
    fireEvent.click(await screen.findByRole("button", { name: "Передать бухгалтеру" }));
    expect(await screen.findByText("Демо Бухгалтеров")).toBeVisible();
    expect(screen.getByRole("group", { name: "Что произойдёт" })).toBeVisible();
    const [, confirm] = screen.getAllByRole("button", { name: "Передать бухгалтеру" });
    fireEvent.click(confirm ?? screen.getByRole("button", { name: "Передать" }));
    expect(await screen.findByText("Письмо передано: Демо Бухгалтеров")).toBeVisible();
    const list = await listOf("Письма, ждущие разбора");
    expect(within(list).queryByText("Запрос КП на стрелочные переводы")).toBeNull();
  });

  it("письмо с неподтверждённым отправителем: пометка в карточке, тип по правилу не поставлен", async () => {
    signIn(REGISTRAR);
    renderAt("/eds/mail/29");
    await heading("Требование о предоставлении документов");
    expect(
      await screen.findByText(
        /Нельзя проверить отправителя: у письма нет отметки почтового сервера/,
      ),
    ).toBeVisible();
  });

  it("форма «Зарегистрировать входящее» предзаполняет вид документа по типу письма", async () => {
    signIn(REGISTRAR);
    renderAt("/eds/mail/29");
    await heading("Требование о предоставлении документов");
    fireEvent.mouseDown(screen.getByRole("combobox", { name: "Сменить тип" }));
    fireEvent.click(await screen.findByTitle("Официальное письмо (госорган, банк, налоговая)"));
    const register = await screen.findByRole("link", { name: "Зарегистрировать как ВХ" });
    fireEvent.click(register);
    expect(
      await screen.findByText(/Из письма: «Требование о предоставлении документов»/),
    ).toBeVisible();
    // у «Официального письма» вид документа — «Письмо госоргана» (код government)
    expect(await screen.findByText("Письмо госоргана")).toBeVisible();
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
